/* ===========================================
   Etapa 2: catálogo de trámites, quejas/reclamos/peticiones,
   notificaciones y líneas de tiempo. Usa las utilidades de app.js.
   =========================================== */

const NOMBRES_TRAMITE_UI = {
    LICENCIA_OBRA: 'Licencia de Obra',
    LICENCIA_FUNCIONAMIENTO: 'Licencia de Funcionamiento',
    PARTIDA_NACIMIENTO: 'Partida de Nacimiento',
    CONSTANCIA_NO_ADEUDO: 'Constancia de No Adeudo',
    CERTIFICADO_DOMICILIO: 'Certificado de Domicilio',
    LICENCIA_EVENTO: 'Licencia para Evento',
    COPIA_CERTIFICADA: 'Copia Certificada de Documento',
};
function nombreTramite(tipo) { return NOMBRES_TRAMITE_UI[tipo] || String(tipo).replace(/_/g, ' '); }

const CLASES_UI = {
    QUEJA: { nombre: 'Queja', icon: 'fa-comment-slash', desc: 'Disconformidad por la atención de un funcionario o un servicio municipal.' },
    RECLAMO: { nombre: 'Reclamo', icon: 'fa-balance-scale', desc: 'Pides corregir un cobro, una multa o un servicio mal prestado.' },
    PETICION: { nombre: 'Petición', icon: 'fa-envelope-open-text', desc: 'Solicitas información, un servicio o presentas una propuesta.' },
};
const ESTADOS_SOL_UI = { RECIBIDA: 'Recibida', EN_ATENCION: 'En atención', ATENDIDA: 'Atendida', IMPROCEDENTE: 'Improcedente' };
const MAX_ADJUNTO_BYTES = 5 * 1024 * 1024;

const AREAS_UI = {
    MESA_PARTES: 'Mesa de Partes', RENTAS: 'Rentas y Tributos', SERVICIOS_PUBLICOS: 'Servicios Públicos',
    OBRAS: 'Obras y Desarrollo Urbano', REGISTRO_CIVIL: 'Registro Civil', ATENCION_CIUDADANO: 'Atención al Ciudadano',
};
const esPersonal = () => !!appState.currentUser && ['admin', 'funcionario'].includes(appState.currentUser.role);

const servState = { clase: '', abrirId: null, categorias: null, catalogo: null };

// ---------- utilidades ----------
function fechaISO(iso) {            // "2026-12-03" -> "03/12/2026" (sin desfase de zona horaria)
    if (!iso) return '—';
    const [y, m, d] = String(iso).slice(0, 10).split('-');
    return `${d}/${m}/${y}`;
}

function abrirModal(html, { ancho = false } = {}) {
    const root = document.getElementById('modal-root');
    const previo = document.activeElement;
    root.innerHTML = `<div class="modal-backdrop" id="mdl-backdrop"><div class="modal ${ancho ? 'modal-wide' : ''}" role="dialog" aria-modal="true">
        <button type="button" class="modal-close" id="mdl-close" aria-label="Cerrar">&times;</button>${html}</div></div>`;
    document.body.classList.add('modal-open');
    const cerrar = () => {
        document.removeEventListener('keydown', onKey);
        root.innerHTML = '';
        document.body.classList.remove('modal-open');
        if (previo && previo.focus) previo.focus();
    };
    const onKey = (e) => { if (e.key === 'Escape') cerrar(); };
    document.addEventListener('keydown', onKey);
    document.getElementById('mdl-close').addEventListener('click', cerrar);
    document.getElementById('mdl-backdrop').addEventListener('mousedown', (e) => { if (e.target.id === 'mdl-backdrop') cerrar(); });
    return { cerrar, el: root.querySelector('.modal') };
}

function vacio(icono, texto) {
    return `<div class="empty-state"><i class="fas ${icono}"></i><p>${esc(texto)}</p></div>`;
}

function timelineHTML(eventos) {
    if (!eventos || !eventos.length) return '<p class="hint">Sin movimientos todavía.</p>';
    return `<ol class="timeline">${eventos.map(e => {
        const clase = e.interna ? 'interna' : (e.tipo === 'pago' || e.ok ? 'pago' : (e.warn ? 'warn' : ''));
        return `<li class="${clase}"><div class="tl-title">${esc(e.titulo)}</div><div class="tl-date">${esc(formatearFecha(e.fecha))}${e.autor ? ' · ' + esc(e.autor) : ''}</div>${e.detalle ? `<div class="tl-text">${esc(e.detalle)}</div>` : ''}</li>`;
    }).join('')}</ol>`;
}

function eventosDeSolicitud(historial) {
    return (historial || []).map(h => ({
        fecha: h.fecha, titulo: h.visible === false ? `${h.evento} (solo personal)` : h.evento, detalle: h.texto, autor: h.autor,
        interna: h.visible === false, ok: /Respuesta oficial/.test(h.evento), warn: /improcedente/i.test(h.evento),
    }));
}

function badgeSolicitud(estado) {
    return `<span class="status-badge status-${esc(estado)}">${esc(ESTADOS_SOL_UI[estado] || estado)}</span>`;
}

function plazoChip(s) {
    if (s.estado === 'ATENDIDA' || s.estado === 'IMPROCEDENTE') {
        return `<span class="meta-chip"><i class="far fa-calendar-check"></i> Respondida el ${esc(formatearFecha(s.fecha_respuesta).slice(0, 10))}</span>`;
    }
    if (s.vencida) return `<span class="meta-chip bad"><i class="fas fa-exclamation-triangle"></i> Plazo vencido hace ${esc(Math.abs(s.dias_restantes))} día(s)</span>`;
    const cerca = s.dias_restantes <= 3;
    return `<span class="meta-chip ${cerca ? 'warn' : ''}"><i class="far fa-clock"></i> Respuesta hasta el ${esc(fechaISO(s.fecha_limite))}${s.dias_restantes === 0 ? ' (hoy)' : ` · ${esc(s.dias_restantes)} día(s)`}</span>`;
}

async function cargarCategorias() {
    if (!servState.categorias) servState.categorias = await apiFetch('/solicitudes/categorias', { method: 'GET', silent: true });
    return servState.categorias;
}
async function cargarCatalogo() {
    if (!servState.catalogo) servState.catalogo = await apiFetch('/tramites/catalogo', { method: 'GET', silent: true });
    return servState.catalogo;
}

// ===========================================
// CATÁLOGO DE TRÁMITES (pestaña "Nuevo Trámite")
// ===========================================
async function initCatalogoTramites() {
    const sel = document.getElementById('nt-tipo-tramite');
    if (!sel) return;
    try {
        const cat = await cargarCatalogo();
        if (!sel.isConnected) return;
        const grupos = {};
        cat.forEach(c => { (grupos[c.categoria] = grupos[c.categoria] || []).push(c); });
        sel.innerHTML = '<option value="">Seleccione...</option>' + Object.entries(grupos).map(([g, items]) =>
            `<optgroup label="${esc(g)}">${items.map(c => `<option value="${esc(c.tipo)}">${esc(c.nombre)} - S/ ${esc(formatCurrency(c.costo))}</option>`).join('')}</optgroup>`).join('');
        sel.addEventListener('change', () => mostrarInfoTramite(sel.value));
    } catch (err) {
        sel.innerHTML = '<option value="">No se pudo cargar el catálogo</option>';
    }
}

function mostrarInfoTramite(tipo) {
    const info = document.getElementById('nt-info');
    const campos = document.getElementById('nt-campos');
    if (!info || !campos) return;
    const c = (servState.catalogo || []).find(x => x.tipo === tipo);
    if (!c) { info.classList.add('hidden'); campos.innerHTML = ''; return; }
    info.classList.remove('hidden');
    info.innerHTML = `<p>${esc(c.descripcion)}</p>
        <b style="font-size:.88rem">Requisitos</b>
        <ul>${c.requisitos.map(r => `<li>${esc(r)}</li>`).join('')}</ul>
        <div class="metas"><span class="meta-chip"><i class="fas fa-tag"></i> S/ ${esc(formatCurrency(c.costo))}</span>
        <span class="meta-chip"><i class="far fa-clock"></i> Atención en ${esc(c.plazo_dias)} día(s) hábiles</span></div>`;
    campos.innerHTML = c.campos.length ? `<div class="campos-tramite"><b style="font-size:.9rem">Datos de la solicitud</b>${c.campos.map(campoHTML).join('')}</div>` : '';
}

function campoHTML(f) {
    const id = `nt-campo-${f.id}`;
    const req = f.requerido ? ' <span style="color:var(--c-danger)">*</span>' : '';
    let ctrl;
    if (f.tipo === 'select') ctrl = `<select id="${id}" class="form-select"><option value="">Seleccione...</option>${f.opciones.map(o => `<option>${esc(o)}</option>`).join('')}</select>`;
    else if (f.tipo === 'textarea') ctrl = `<textarea id="${id}" class="form-input is-area" maxlength="300"></textarea>`;
    else if (f.tipo === 'number') ctrl = `<input id="${id}" type="number" inputmode="numeric" class="form-input" min="${esc(f.min ?? 1)}" ${f.max ? `max="${esc(f.max)}"` : ''}>`;
    else if (f.tipo === 'date') ctrl = `<input id="${id}" type="date" class="form-input" min="${new Date().toISOString().slice(0, 10)}">`;
    else ctrl = `<input id="${id}" type="text" class="form-input" maxlength="300">`;
    return `<div class="form-group"><label for="${id}">${esc(f.label)}${req}</label>${ctrl}</div>`;
}

/** Devuelve los datos del formulario del trámite, o null si falta algo (ya avisa al usuario). */
function leerCamposTramite() {
    const tipo = document.getElementById('nt-tipo-tramite').value;
    const c = (servState.catalogo || []).find(x => x.tipo === tipo);
    const detalles = {};
    if (!c) return detalles;
    for (const f of c.campos) {
        const el = document.getElementById(`nt-campo-${f.id}`);
        const v = el ? el.value.trim() : '';
        if (!v && f.requerido) {
            showAlert('Falta información', `Complete el campo: ${f.label}.`, 'warning');
            if (el) el.focus();
            return null;
        }
        if (v) detalles[f.id] = v;
    }
    return detalles;
}

function detallesHTML(tramite) {
    const d = tramite.detalles;
    if (!d || !Object.keys(d).length) return '';
    const cat = (servState.catalogo || []).find(x => x.tipo === tramite.tipo);
    const etiqueta = (k) => (cat && (cat.campos.find(f => f.id === k) || {}).label) || k.replace(/_/g, ' ');
    return `<dl class="detail-grid">${Object.entries(d).map(([k, v]) =>
        `<div><dt>${esc(etiqueta(k))}</dt><dd>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</dd></div>`).join('')}</dl>`;
}

async function cargarSeguimientoTramite(contenedor) {
    const marca = contenedor && contenedor.querySelector('[data-seguimiento-tramite]');
    if (!marca) return;
    try {
        const ev = await apiFetch(`/tramites/${marca.dataset.seguimientoTramite}/seguimiento`, { method: 'GET', silent: true });
        if (marca.isConnected) marca.innerHTML = timelineHTML(ev.map(e => ({ ...e, ok: e.tipo === 'pago', warn: /observado|rechazado/i.test(e.titulo) })));
    } catch (err) {
        if (marca.isConnected) marca.innerHTML = '<p class="hint">No se pudo cargar el seguimiento.</p>';
    }
}

// ===========================================
// CIUDADANO: QUEJAS, RECLAMOS Y PETICIONES
// ===========================================
async function renderMisSolicitudes() {
    dashboardContent.innerHTML = `<div class="card">
        <h2 class="card-header">Quejas, Reclamos y Peticiones</h2>
        <div class="module-bar">
          <div class="chips" id="sol-chips" role="group" aria-label="Filtrar por tipo">
            ${[['', 'Todas'], ['QUEJA', 'Quejas'], ['RECLAMO', 'Reclamos'], ['PETICION', 'Peticiones']].map(([v, l]) =>
                `<button type="button" class="chip ${servState.clase === v ? 'active' : ''}" data-clase="${v}">${l}</button>`).join('')}
          </div>
          <button type="button" class="btn btn-primario" id="sol-nueva"><i class="fas fa-plus"></i> Nueva solicitud</button>
        </div>
        <div id="sol-lista">${RENDER.loadingState()}</div></div>`;
    document.getElementById('sol-nueva').addEventListener('click', () => renderNuevaSolicitud());
    document.getElementById('sol-chips').addEventListener('click', (e) => {
        const b = e.target.closest('.chip'); if (!b) return;
        servState.clase = b.dataset.clase;
        document.querySelectorAll('#sol-chips .chip').forEach(x => x.classList.toggle('active', x === b));
        cargarListaSolicitudes();
    });
    await cargarListaSolicitudes();
    if (servState.abrirId) { const id = servState.abrirId; servState.abrirId = null; abrirDetalleSolicitud(id); }
}

async function cargarListaSolicitudes() {
    const cont = document.getElementById('sol-lista');
    if (!cont) return;
    cont.innerHTML = RENDER.loadingState();
    try {
        const qs = servState.clase ? `?clase=${servState.clase}` : '';
        const lista = await apiFetch(`/solicitudes/mias${qs}`, { method: 'GET', silent: true });
        if (!cont.isConnected) return;
        if (!lista.length) {
            cont.innerHTML = vacio('fa-inbox', 'Aún no tienes solicitudes. Usa "Nueva solicitud" para registrar una queja, un reclamo o una petición y recibir un código de seguimiento.');
            return;
        }
        cont.innerHTML = `<div class="sol-list">${lista.map(s => `
            <button type="button" class="sol-card ${esc(s.clase)}" data-id="${esc(s.id)}">
              <div class="top"><div><span class="cod">${esc(s.codigo)}</span> · <span style="font-size:.8rem;color:var(--c-muted)">${esc(s.clase_nombre)} · ${esc(s.categoria_nombre)}</span>
                <div class="asunto">${esc(s.asunto)}</div></div>${badgeSolicitud(s.estado)}</div>
              <div class="meta">${plazoChip(s)}<span class="meta-chip"><i class="far fa-calendar"></i> Registrada el ${esc(formatearFecha(s.fecha_creacion).slice(0, 10))}</span></div>
            </button>`).join('')}</div>`;
        cont.querySelectorAll('.sol-card').forEach(b => b.addEventListener('click', () => abrirDetalleSolicitud(b.dataset.id)));
    } catch (err) {
        if (cont.isConnected) cont.innerHTML = `<p class="text-center py-8" style="color:var(--c-danger)">${esc(err.message)}</p>`;
    }
}

async function abrirDetalleSolicitud(id) {
    dashboardContent.innerHTML = `<div class="card">${RENDER.loadingState()}</div>`;
    let s;
    try { s = await apiFetch(`/solicitudes/${id}`, { method: 'GET', silent: true }); }
    catch (err) { dashboardContent.innerHTML = RENDER.errorTab(err.message); return; }
    if (appState.currentTab !== 'solicitudes') return;
    const abierta = s.estado === 'RECIBIDA' || s.estado === 'EN_ATENCION';
    const docs = s.documentos.length ? `<ul class="border rounded-lg divide-y">${s.documentos.map(d => `
        <li class="flex items-center justify-between py-2 px-3"><span class="truncate flex-1">${esc(d.nombre)}</span>
        <button type="button" class="btn btn-secundario btn-doc-download" data-url="${esc(d.url)}" data-nombre="${esc(d.nombre)}" style="padding:2px 8px;font-size:12px"><i class="fas fa-download"></i> Descargar</button></li>`).join('')}</ul>` : '<p class="hint">Sin adjuntos.</p>';
    const respuesta = s.respuesta ? `<div class="official-reply ${s.estado === 'IMPROCEDENTE' ? 'deny' : ''}">
        <h4><i class="fas fa-stamp"></i> ${s.estado === 'IMPROCEDENTE' ? 'Declarada improcedente' : 'Respuesta oficial'}</h4>
        <div class="text-block" style="background:#fff;white-space:pre-wrap">${esc(s.respuesta)}</div>
        <div class="who">${esc(s.respondido_por || '')} · ${esc(formatearFecha(s.fecha_respuesta))}</div></div>` : '';
    dashboardContent.innerHTML = `<div class="card">
        <button type="button" class="btn btn-ghost" id="sol-volver" style="margin-bottom:.75rem"><i class="fas fa-arrow-left"></i> Volver</button>
        <div class="module-bar"><div><span class="cod font-mono" style="color:var(--c-muted);font-weight:700">${esc(s.codigo)}</span>
          <h2 class="card-header" style="margin:.15rem 0 0">${esc(s.asunto)}</h2></div>${badgeSolicitud(s.estado)}</div>
        <div class="meta" style="display:flex;gap:.45rem;flex-wrap:wrap">${plazoChip(s)}</div>
        <dl class="detail-grid">
          <div><dt>Tipo</dt><dd>${esc(s.clase_nombre)}</dd></div><div><dt>Categoría</dt><dd>${esc(s.categoria_nombre)}</dd></div>
          <div><dt>Registrada</dt><dd>${esc(formatearFecha(s.fecha_creacion))}</dd></div>
          ${s.area_nombre ? `<div><dt>Área responsable</dt><dd>${esc(s.area_nombre)}</dd></div>` : ''}
          ${s.ubicacion ? `<div><dt>Ubicación</dt><dd>${esc(s.ubicacion)}</dd></div>` : ''}</dl>
        <div class="section-title">Descripción</div><div class="text-block">${esc(s.descripcion)}</div>
        ${respuesta}
        <div class="section-title">Adjuntos</div>${docs}
        ${abierta ? `<form id="sol-adjuntar" class="filter-bar" style="margin-top:.75rem"><div class="field" style="flex:2 1 14rem"><input type="file" id="sol-archivos" multiple accept=".pdf,.jpg,.jpeg,.png" class="form-input" style="padding-right:.85rem"></div>
            <button class="btn btn-secundario" type="submit"><i class="fas fa-paperclip"></i> Agregar adjuntos</button></form>` : ''}
        <div class="section-title">Seguimiento</div>${timelineHTML(eventosDeSolicitud(s.historial))}
        ${abierta ? `<div class="section-title">Agregar información</div>
          <form id="sol-comentar"><textarea id="sol-comentario" class="form-input is-area" maxlength="1000" placeholder="Escribe aquí datos adicionales para el área que atiende tu caso..." style="min-height:5rem"></textarea>
          <button class="btn btn-primario" type="submit" style="margin-top:.6rem"><i class="fas fa-paper-plane"></i> Enviar</button></form>` : ''}
    </div>`;
    document.getElementById('sol-volver').addEventListener('click', renderMisSolicitudes);
    const fa = document.getElementById('sol-adjuntar');
    if (fa) fa.addEventListener('submit', async (e) => {
        e.preventDefault();
        const files = Array.from(document.getElementById('sol-archivos').files);
        const error = validarArchivos(files);
        if (error || !files.length) { showAlert('Adjuntos', error || 'Seleccione al menos un archivo.', 'warning'); return; }
        const fd = new FormData(); files.forEach(f => fd.append('files', f));
        try { await apiFetch(`/solicitudes/${id}/adjuntos`, { method: 'POST', body: fd }); abrirDetalleSolicitud(id); } catch (err) { /* ya notificado */ }
    });
    const fc = document.getElementById('sol-comentar');
    if (fc) fc.addEventListener('submit', async (e) => {
        e.preventDefault();
        const texto = document.getElementById('sol-comentario').value.trim();
        if (texto.length < 3) { showAlert('Comentario', 'Escribe al menos 3 caracteres.', 'warning'); return; }
        try { await apiFetch(`/solicitudes/${id}/comentarios`, { method: 'POST', body: JSON.stringify({ texto }) }); abrirDetalleSolicitud(id); } catch (err) { /* ya notificado */ }
    });
}

function validarArchivos(files) {
    for (const f of files) {
        if (f.size > MAX_ADJUNTO_BYTES) return `${f.name}: supera los 5 MB.`;
        if (!/(pdf|image\/(jpeg|png))/.test(f.type)) return `${f.name}: solo se admiten PDF, JPG o PNG.`;
    }
    return '';
}

async function renderNuevaSolicitud(claseInicial) {
    dashboardContent.innerHTML = `<div class="card">${RENDER.loadingState()}</div>`;
    let cats;
    try { cats = await cargarCategorias(); } catch (err) { dashboardContent.innerHTML = RENDER.errorTab(err.message); return; }
    if (appState.currentTab !== 'solicitudes') return;
    const inicial = claseInicial || 'QUEJA';
    dashboardContent.innerHTML = `<div class="card">
      <button type="button" class="btn btn-ghost" id="ns-volver" style="margin-bottom:.75rem"><i class="fas fa-arrow-left"></i> Volver</button>
      <h2 class="card-header">Nueva solicitud</h2>
      <form id="ns-form" novalidate style="max-width:46rem">
        <div class="clase-picker" role="radiogroup" aria-label="Tipo de solicitud">
          ${cats.map(c => `<label class="clase-opt"><input type="radio" name="ns-clase" value="${esc(c.clase)}" ${c.clase === inicial ? 'checked' : ''}>
            <div><i class="fas ${CLASES_UI[c.clase].icon}"></i><b>${esc(c.nombre)}</b><small>${esc(CLASES_UI[c.clase].desc)}</small></div></label>`).join('')}
        </div>
        <div class="form-group"><label for="ns-categoria">Categoría</label><select id="ns-categoria" class="form-select"></select><div class="hint" id="ns-plazo"></div></div>
        <div class="form-group"><label for="ns-asunto">Asunto</label><input id="ns-asunto" class="form-input" maxlength="150" placeholder="Resume el tema en una frase" style="padding-right:.85rem"></div>
        <div class="form-group"><label for="ns-descripcion">Descripción de los hechos o de lo que solicitas</label>
          <textarea id="ns-descripcion" class="form-input is-area" maxlength="3000" placeholder="Indica qué ocurrió, cuándo y dónde, y qué esperas que haga la municipalidad."></textarea>
          <div class="hint"><span id="ns-contador">0</span>/3000 · mínimo 20 caracteres</div></div>
        <div class="form-group"><label for="ns-ubicacion">Ubicación (opcional)</label><input id="ns-ubicacion" class="form-input" maxlength="255" placeholder="Calle, referencia o lugar del hecho" style="padding-right:.85rem"></div>
        <div class="form-group"><label for="ns-archivos">Adjuntos (opcional)</label><input type="file" id="ns-archivos" multiple accept=".pdf,.jpg,.jpeg,.png" class="form-input" style="padding-right:.85rem">
          <div class="hint">PDF, JPG o PNG, hasta 5 MB cada uno: fotos, recibos, documentos.</div></div>
        <div id="ns-error" class="pay-alert hidden"></div>
        <button type="submit" class="btn btn-primario" id="ns-enviar"><i class="fas fa-paper-plane"></i> Registrar solicitud</button>
      </form></div>`;
    const actualizarCategorias = () => {
        const clase = document.querySelector('input[name="ns-clase"]:checked').value;
        const lista = cats.find(c => c.clase === clase).categorias;
        document.getElementById('ns-categoria').innerHTML = lista.map(c => `<option value="${esc(c.id)}" data-plazo="${esc(c.plazo_dias)}">${esc(c.nombre)}</option>`).join('');
        mostrarPlazo();
    };
    const mostrarPlazo = () => {
        const op = document.getElementById('ns-categoria').selectedOptions[0];
        document.getElementById('ns-plazo').textContent = op ? `Plazo de atención: ${op.dataset.plazo} días hábiles desde el registro.` : '';
    };
    document.querySelectorAll('input[name="ns-clase"]').forEach(r => r.addEventListener('change', actualizarCategorias));
    document.getElementById('ns-categoria').addEventListener('change', mostrarPlazo);
    document.getElementById('ns-descripcion').addEventListener('input', (e) => { document.getElementById('ns-contador').textContent = e.target.value.length; });
    document.getElementById('ns-volver').addEventListener('click', renderMisSolicitudes);
    actualizarCategorias();

    document.getElementById('ns-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const err = document.getElementById('ns-error');
        const mostrarError = (m) => { err.textContent = m; err.classList.remove('hidden'); };
        err.classList.add('hidden');
        const cuerpo = {
            clase: document.querySelector('input[name="ns-clase"]:checked').value,
            categoria: document.getElementById('ns-categoria').value,
            asunto: document.getElementById('ns-asunto').value.trim(),
            descripcion: document.getElementById('ns-descripcion').value.trim(),
            ubicacion: document.getElementById('ns-ubicacion').value.trim() || null,
        };
        if (cuerpo.asunto.length < 5) return mostrarError('El asunto debe tener al menos 5 caracteres.');
        if (cuerpo.descripcion.length < 20) return mostrarError('Describe el caso con al menos 20 caracteres.');
        const files = Array.from(document.getElementById('ns-archivos').files);
        const malo = validarArchivos(files);
        if (malo) return mostrarError(malo);
        const btn = document.getElementById('ns-enviar'); btn.disabled = true;
        try {
            let s = await apiFetch('/solicitudes/', { method: 'POST', body: JSON.stringify(cuerpo) });
            let aviso = '';
            if (files.length) {
                const fd = new FormData(); files.forEach(f => fd.append('files', f));
                try { s = await apiFetch(`/solicitudes/${s.id}/adjuntos`, { method: 'POST', body: fd, silent: true }); }
                catch (e2) { aviso = 'Tu solicitud se registró, pero no se pudieron subir los adjuntos. Puedes agregarlos desde el detalle.'; }
            }
            mostrarConfirmacionSolicitud(s, aviso);
            actualizarContadorNotificaciones();
        } catch (e3) { btn.disabled = false; }
    });
}

function mostrarConfirmacionSolicitud(s, aviso) {
    dashboardContent.innerHTML = `<div class="card"><div class="success-box">
        <div class="pay-check" style="margin:0 auto"><i class="fas fa-check"></i></div>
        <h2 style="font-size:1.4rem;font-weight:800;margin:.8rem 0 0">¡Solicitud registrada!</h2>
        <p style="color:var(--c-muted)">Guarda tu código de seguimiento</p>
        <div class="code" id="sol-codigo">${esc(s.codigo)}</div>
        <p style="color:var(--c-muted)">${esc(s.clase_nombre)} · ${esc(s.categoria_nombre)}</p>
        <div style="margin:.6rem 0">${plazoChip(s)}</div>
        ${aviso ? `<div class="pay-hint" style="display:inline-block">${esc(aviso)}</div>` : ''}
        <div style="display:flex;gap:.6rem;justify-content:center;flex-wrap:wrap;margin-top:1.1rem">
          <button class="btn btn-primario" id="cf-ver" type="button"><i class="fas fa-eye"></i> Ver seguimiento</button>
          <button class="btn btn-secundario" id="cf-lista" type="button">Mis solicitudes</button></div></div></div>`;
    document.getElementById('cf-ver').addEventListener('click', () => abrirDetalleSolicitud(s.id));
    document.getElementById('cf-lista').addEventListener('click', renderMisSolicitudes);
}

// ===========================================
// ADMIN: BANDEJA DE QUEJAS, RECLAMOS Y PETICIONES
// ===========================================
async function renderAdminSolicitudes() {
    dashboardContent.innerHTML = `<div class="card"><h2 class="card-header">Quejas, Reclamos y Peticiones</h2>
        <div id="as-resumen" class="stat-grid" style="margin-bottom:1.25rem"></div>
        <form id="as-filtros" class="filter-bar">
          <div class="field" style="flex:2 1 14rem"><label for="as-q">Buscar</label><input id="as-q" class="form-input" placeholder="Código, asunto, DNI o nombre" style="padding-right:.85rem"></div>
          <div class="field"><label for="as-clase">Tipo</label><select id="as-clase" class="form-select"><option value="">Todos</option><option value="QUEJA">Quejas</option><option value="RECLAMO">Reclamos</option><option value="PETICION">Peticiones</option></select></div>
          <div class="field"><label for="as-estado">Estado</label><select id="as-estado" class="form-select"><option value="">Todos</option>${Object.entries(ESTADOS_SOL_UI).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
          ${appState.currentUser.role === 'admin' ? `<div class="field"><label for="as-area">Área</label><select id="as-area" class="form-select"><option value="">Todas</option>${Object.entries(AREAS_UI).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>` : `<div class="field"><label>Su área</label><div class="meta-chip">${esc(AREAS_UI[appState.currentUser.area] || '—')}</div></div>`}
          <label class="chip" style="display:inline-flex;gap:.4rem;align-items:center;cursor:pointer"><input type="checkbox" id="as-vencidas"> Solo vencidas</label>
          <button class="btn btn-primario" type="submit"><i class="fas fa-filter"></i> Filtrar</button>
        </form><div id="as-lista">${RENDER.loadingState()}</div></div>`;
    document.getElementById('as-filtros').addEventListener('submit', (e) => { e.preventDefault(); cargarAdminSolicitudes(); });
    cargarResumenSolicitudes();
    await cargarAdminSolicitudes();
    if (servState.abrirId) { const id = servState.abrirId; servState.abrirId = null; gestionarSolicitud(id); }
}

async function cargarResumenSolicitudes() {
    const cont = document.getElementById('as-resumen');
    try {
        const r = await apiFetch('/solicitudes/admin/resumen', { method: 'GET', silent: true });
        if (!cont || !cont.isConnected) return;
        const card = (l, v, color) => `<div class="stat-card"><div class="stat-label">${l}</div><div class="stat-value" ${color ? `style="color:${color}"` : ''}>${esc(v)}</div></div>`;
        cont.innerHTML = card('Recibidas', r.recibidas, 'var(--c-primary)') + card('En atención', r.en_atencion, 'var(--c-warning)') +
            card('Atendidas', r.atendidas, 'var(--c-success)') + card('Plazo vencido', r.vencidas, r.vencidas ? 'var(--c-danger)' : '');
    } catch (err) { /* el resumen es opcional */ }
}

async function cargarAdminSolicitudes() {
    const cont = document.getElementById('as-lista');
    if (!cont) return;
    cont.innerHTML = RENDER.loadingState();
    const qs = new URLSearchParams();
    [['q', 'as-q'], ['clase', 'as-clase'], ['estado', 'as-estado'], ['area', 'as-area']].forEach(([k, id]) => { const el = document.getElementById(id); const v = el ? el.value.trim() : ''; if (v) qs.set(k, v); });
    if (document.getElementById('as-vencidas').checked) qs.set('vencidas', 'true');
    try {
        const lista = await apiFetch(`/solicitudes/admin/all?${qs}`, { method: 'GET', silent: true });
        if (!cont.isConnected) return;
        if (!lista.length) { cont.innerHTML = vacio('fa-inbox', 'No hay solicitudes con esos filtros.'); return; }
        cont.innerHTML = `<div class="table-wrapper"><table class="table"><thead><tr><th>Código</th><th>Ciudadano</th><th>Asunto</th><th>Estado</th><th>Plazo</th><th></th></tr></thead><tbody>
          ${lista.map(s => `<tr>
            <td class="font-mono" style="font-size:.82rem"><b>${esc(s.codigo)}</b><div style="color:var(--c-muted);font-family:Inter,sans-serif">${esc(s.clase_nombre)}</div></td>
            <td>${esc(s.ciudadano_nombre)}<div style="font-size:.78rem;color:var(--c-muted)">DNI ${esc(s.ciudadano_dni)}</div></td>
            <td style="max-width:20rem">${esc(s.asunto)}<div style="font-size:.78rem;color:var(--c-muted)">${esc(s.categoria_nombre)}${s.area_nombre ? ' · ' + esc(s.area_nombre) : ''}</div></td>
            <td>${badgeSolicitud(s.estado)}</td><td>${plazoChip(s)}</td>
            <td><button class="btn btn-secundario btn-gestionar-sol" data-id="${esc(s.id)}" style="padding:.35rem .8rem;font-size:.82rem"><i class="fas fa-pen"></i> Gestionar</button></td></tr>`).join('')}
          </tbody></table></div>`;
        cont.querySelectorAll('.btn-gestionar-sol').forEach(b => b.addEventListener('click', () => gestionarSolicitud(b.dataset.id)));
    } catch (err) {
        if (cont.isConnected) cont.innerHTML = `<p class="text-center py-8" style="color:var(--c-danger)">${esc(err.message)}</p>`;
    }
}

async function gestionarSolicitud(id) {
    let s;
    try { s = await apiFetch(`/solicitudes/${id}`, { method: 'GET', silent: true }); }
    catch (err) { showAlert('Error', err.message, 'error'); return; }
    const abierta = s.estado === 'RECIBIDA' || s.estado === 'EN_ATENCION';
    const m = abrirModal(`<div class="modal-head"><h2>${esc(s.codigo)} · ${esc(s.asunto)}</h2><div class="sub">${esc(s.clase_nombre)} · ${esc(s.categoria_nombre)}</div></div>
      <div class="modal-body">
        <div style="display:flex;gap:.45rem;flex-wrap:wrap;align-items:center">${badgeSolicitud(s.estado)} ${plazoChip(s)} ${s.area_nombre ? `<span class="meta-chip"><i class="fas fa-sitemap"></i> ${esc(s.area_nombre)}</span>` : ''}</div>
        <dl class="detail-grid">
          <div><dt>Ciudadano</dt><dd>${esc(s.ciudadano_nombre)}</dd></div><div><dt>DNI</dt><dd>${esc(s.ciudadano_dni)}</dd></div>
          <div><dt>Teléfono</dt><dd>${esc(s.ciudadano_telefono || '—')}</dd></div><div><dt>Correo</dt><dd>${esc(s.ciudadano_email || '—')}</dd></div>
          ${s.ubicacion ? `<div><dt>Ubicación</dt><dd>${esc(s.ubicacion)}</dd></div>` : ''}</dl>
        <div class="text-block">${esc(s.descripcion)}</div>
        ${s.documentos.length ? `<div class="section-title">Adjuntos</div><ul>${s.documentos.map(d => `<li><button type="button" class="btn-doc-download" style="color:#2563eb;text-decoration:underline" data-url="${esc(d.url)}" data-nombre="${esc(d.nombre)}">${esc(d.nombre)}</button></li>`).join('')}</ul>` : ''}
        <div class="section-title">Historial</div>${timelineHTML(eventosDeSolicitud(s.historial))}
        ${s.respuesta ? `<div class="official-reply ${s.estado === 'IMPROCEDENTE' ? 'deny' : ''}"><h4>Respuesta oficial</h4><div class="text-block" style="background:#fff">${esc(s.respuesta)}</div></div>` : ''}
        ${abierta ? `<form id="gd-form" class="filter-bar" style="margin-top:1rem"><div class="section-title" style="flex-basis:100%;margin:0">Derivar a otra área</div>
          <div class="field"><label for="gd-area">Área</label><select id="gd-area" class="form-select">${Object.entries(AREAS_UI).filter(([k]) => k !== s.area).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
          <div class="field" style="flex:2 1 14rem"><label for="gd-motivo">Motivo</label><input id="gd-motivo" class="form-input" maxlength="300" placeholder="Por qué corresponde a esa área" style="padding-right:.85rem"></div>
          <button class="btn btn-secundario" type="submit"><i class="fas fa-share"></i> Derivar</button></form>
          <div id="gd-error" class="pay-alert hidden"></div>` : ''}
        ${abierta ? `<form id="gs-form"><div class="section-title">Atender</div>
          <div class="form-group"><label for="gs-estado">Nuevo estado</label><select id="gs-estado" class="form-select">
            <option value="EN_ATENCION">En atención (derivado / en proceso)</option><option value="ATENDIDA">Atendida (cerrar con respuesta oficial)</option><option value="IMPROCEDENTE">Improcedente (cerrar con motivo)</option></select></div>
          <div class="form-group"><label for="gs-respuesta">Mensaje o respuesta oficial para el ciudadano <span id="gs-oblig" style="color:var(--c-danger)" class="hidden">*</span></label>
            <textarea id="gs-respuesta" class="form-input is-area" maxlength="3000" style="min-height:6rem"></textarea><div class="hint">Al cerrar, la respuesta es obligatoria y ya no se podrá reabrir.</div></div>
          <div class="form-group"><label for="gs-nota">Nota interna (el ciudadano no la ve)</label><textarea id="gs-nota" class="form-input is-area" maxlength="1000" style="min-height:3.5rem"></textarea></div>
          <div id="gs-error" class="pay-alert hidden"></div>
          <button class="btn btn-primario" type="submit"><i class="fas fa-save"></i> Guardar</button></form>` : '<p class="hint" style="margin-top:1rem">Esta solicitud está cerrada.</p>'}
      </div>`, { ancho: true });
    const fd = m.el.querySelector('#gd-form');
    if (fd) fd.addEventListener('submit', async (e) => {
        e.preventDefault();
        const err = m.el.querySelector('#gd-error'); err.classList.add('hidden');
        const motivo = fd.querySelector('#gd-motivo').value.trim();
        if (motivo.length < 5) { err.textContent = 'Indique el motivo de la derivación (mínimo 5 caracteres).'; err.classList.remove('hidden'); return; }
        try {
            await apiFetch(`/solicitudes/${id}/derivar`, { method: 'PUT', body: JSON.stringify({ area: fd.querySelector('#gd-area').value, motivo }), silent: true });
            m.cerrar();
            showAlert('Caso derivado', 'El ciudadano fue notificado del cambio de área.', 'success');
            cargarAdminSolicitudes(); cargarResumenSolicitudes();
        } catch (e2) { err.textContent = e2.message; err.classList.remove('hidden'); }
    });
    const form = m.el.querySelector('#gs-form');
    if (!form) return;
    const est = form.querySelector('#gs-estado');
    est.addEventListener('change', () => form.querySelector('#gs-oblig').classList.toggle('hidden', est.value === 'EN_ATENCION'));
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const err = form.querySelector('#gs-error'); err.classList.add('hidden');
        const respuesta = form.querySelector('#gs-respuesta').value.trim();
        if (est.value !== 'EN_ATENCION' && respuesta.length < 10) { err.textContent = 'Redacte la respuesta oficial (mínimo 10 caracteres) para cerrar la solicitud.'; err.classList.remove('hidden'); return; }
        try {
            await apiFetch(`/solicitudes/${id}/gestionar`, { method: 'PUT', body: JSON.stringify({ estado: est.value, respuesta: respuesta || null, nota_interna: form.querySelector('#gs-nota').value.trim() || null }) });
            m.cerrar();
            showAlert('Listo', 'La solicitud se actualizó y el ciudadano fue notificado.', 'success');
            cargarAdminSolicitudes(); cargarResumenSolicitudes();
        } catch (e2) { /* ya notificado */ }
    });
}

// ===========================================
// NOTIFICACIONES (campana)
// ===========================================
let notifTimer = null;
const ICONOS_NOTIF = { TRAMITE: 'fa-folder-open', PAGO: 'fa-receipt', QUEJA: 'fa-comment-slash', RECLAMO: 'fa-balance-scale', PETICION: 'fa-envelope-open-text', SISTEMA: 'fa-info-circle' };

function pintarBadge(n) {
    const b = document.getElementById('notif-badge');
    if (!b) return;
    b.textContent = n > 99 ? '99+' : String(n);
    b.classList.toggle('hidden', !n);
}

async function actualizarContadorNotificaciones() {
    if (!appState.currentUser) return;
    try { pintarBadge((await apiFetch('/notificaciones/contador', { method: 'GET', silent: true })).no_leidas); } catch (e) { /* silencioso */ }
}

function iniciarNotificaciones() {
    detenerNotificaciones();
    actualizarContadorNotificaciones();
    cargarCatalogo().catch(() => {});
    notifTimer = setInterval(() => {
        if (!appState.currentUser) return detenerNotificaciones();
        if (!document.hidden) actualizarContadorNotificaciones();
    }, 45000);
}
function detenerNotificaciones() { if (notifTimer) clearInterval(notifTimer); notifTimer = null; }

function cerrarPanelNotificaciones() {
    const p = document.getElementById('notif-panel'); if (!p) return;
    p.classList.add('hidden');
    document.getElementById('notif-btn').setAttribute('aria-expanded', 'false');
}

async function abrirPanelNotificaciones() {
    const p = document.getElementById('notif-panel');
    p.classList.remove('hidden');
    document.getElementById('notif-btn').setAttribute('aria-expanded', 'true');
    p.innerHTML = `<div class="notif-head">Notificaciones</div><div class="notif-empty">Cargando...</div>`;
    try {
        const d = await apiFetch('/notificaciones/?limite=30', { method: 'GET', silent: true });
        pintarBadge(d.no_leidas);
        p.innerHTML = `<div class="notif-head"><span>Notificaciones</span>${d.no_leidas ? '<button type="button" id="notif-leer-todas">Marcar todas como leídas</button>' : ''}</div>
          <div class="notif-list">${d.items.length ? d.items.map(n => `
            <button type="button" class="notif-item ${n.leida ? '' : 'unread'}" data-id="${esc(n.id)}" data-ref="${esc(n.referencia || '')}">
              <span class="notif-ico"><i class="fas ${ICONOS_NOTIF[n.tipo] || 'fa-bell'}"></i></span>
              <span><div class="t">${esc(n.titulo)}</div><div class="m">${esc(n.mensaje)}</div><div class="f">${esc(formatearFecha(n.fecha))}</div></span>
            </button>`).join('') : '<div class="notif-empty">No tienes notificaciones.</div>'}</div>`;
    } catch (err) {
        p.innerHTML = `<div class="notif-head">Notificaciones</div><div class="notif-empty">No se pudieron cargar.</div>`;
    }
}

function irAReferencia(ref) {
    if (!ref || !appState.currentUser) return;
    const [tipo, id] = ref.split(':');
    const rol = appState.currentUser.role;
    if (tipo === 'tramite') loadTabContent(esPersonal() ? 'revision-tramites' : 'mis-tramites', rol);
    else if (tipo === 'deuda') loadTabContent('mis-deudas', rol);
    else if (tipo === 'solicitud') { servState.abrirId = id; loadTabContent('solicitudes', rol); }
}

document.addEventListener('click', async (e) => {
    const btn = e.target.closest('#notif-btn');
    const panel = document.getElementById('notif-panel');
    if (btn) {
        if (panel.classList.contains('hidden')) abrirPanelNotificaciones(); else cerrarPanelNotificaciones();
        return;
    }
    const todas = e.target.closest('#notif-leer-todas');
    if (todas) {
        try { await apiFetch('/notificaciones/leer-todas', { method: 'POST', silent: true }); pintarBadge(0); abrirPanelNotificaciones(); } catch (err) { /* silencioso */ }
        return;
    }
    const item = e.target.closest('.notif-item');
    if (item) {
        const { id, ref } = item.dataset;
        cerrarPanelNotificaciones();
        try { const r = await apiFetch(`/notificaciones/${id}/leida`, { method: 'POST', silent: true }); pintarBadge(r.no_leidas); } catch (err) { /* silencioso */ }
        irAReferencia(ref);
        return;
    }
    if (panel && !panel.classList.contains('hidden') && !e.target.closest('#notif-panel')) cerrarPanelNotificaciones();
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') cerrarPanelNotificaciones(); });

// ===========================================
// REPORTES Y AUDITORÍA (administrador)
// ===========================================
async function renderReportes() {
    dashboardContent.innerHTML = `<div class="card"><h2 class="card-header">Reportes de gestión</h2><div id="rp-cuerpo">${RENDER.loadingState()}</div></div>
        <div class="card" style="margin-top:1.25rem"><h2 class="card-header">Auditoría: quién hizo qué</h2>
        <form id="au-filtros" class="filter-bar">
          <div class="field" style="flex:2 1 14rem"><label for="au-q">Buscar</label><input id="au-q" class="form-input" placeholder="DNI, nombre, código o detalle" style="padding-right:.85rem"></div>
          <div class="field"><label for="au-accion">Acción</label><select id="au-accion" class="form-select"><option value="">Todas</option>
            ${['TRAMITE_ESTADO', 'SOLICITUD_EN_ATENCION', 'SOLICITUD_ATENDIDA', 'SOLICITUD_IMPROCEDENTE', 'SOLICITUD_DERIVADA', 'USUARIO_CREADO', 'CLAVE_RESETEADA', 'CLAVE_CODIGO_SOLICITADO', 'CLAVE_RESTABLECIDA', 'CUENTA_CREADA'].map(a => `<option>${a}</option>`).join('')}</select></div>
          <button class="btn btn-primario" type="submit"><i class="fas fa-filter"></i> Filtrar</button></form>
        <div id="au-lista">${RENDER.loadingState()}</div></div>`;
    document.getElementById('au-filtros').addEventListener('submit', (e) => { e.preventDefault(); cargarAuditoria(); });
    cargarAuditoria();
    const cuerpo = document.getElementById('rp-cuerpo');
    try {
        const d = await apiFetch('/admin/reportes', { method: 'GET', silent: true });
        if (!cuerpo.isConnected) return;
        const sol = d.solicitudes;
        const kpi = (l, v, sub, color) => `<div class="stat-card"><div class="stat-label">${esc(l)}</div><div class="stat-value" ${color ? `style="color:${color}"` : ''}>${esc(v)}</div>${sub ? `<div class="hint">${esc(sub)}</div>` : ''}</div>`;
        const barras = (obj, nombres) => { const max = Math.max(1, ...Object.values(obj)); return Object.entries(obj).map(([k, n]) => `<div class="bar-row"><span>${esc(nombres[k] || k)}</span><div class="bar"><i style="width:${(100 * n / max).toFixed(0)}%"></i></div><b>${esc(n)}</b></div>`).join('') || '<p class="hint">Sin datos todavía.</p>'; };
        cuerpo.innerHTML = `<div class="report-grid">
            ${kpi('Solicitudes', sol.total, `${sol.abiertas} abiertas`)}
            ${kpi('Atendidas dentro del plazo', sol.en_plazo_pct === null ? '—' : sol.en_plazo_pct + ' %', `de ${sol.atendidas} cerradas`, sol.en_plazo_pct !== null && sol.en_plazo_pct < 70 ? 'var(--c-danger)' : 'var(--c-success)')}
            ${kpi('Tiempo promedio de respuesta', sol.tiempo_promedio_dias === null ? '—' : (sol.tiempo_promedio_dias < 1 ? 'menos de 1 día' : sol.tiempo_promedio_dias + ' días'), 'desde el registro')}
            ${kpi('Plazo vencido', sol.vencidas, 'casos abiertos fuera de plazo', sol.vencidas ? 'var(--c-danger)' : '')}
            ${kpi('Trámites', d.tramites.total, `${(d.tramites.por_estado.EN_EVALUACION || 0)} en evaluación`)}</div>
          <div class="section-title">Por área</div>
          <div class="table-wrapper"><table class="table"><thead><tr><th>Área</th><th>Solicitudes</th><th>Abiertas</th><th>Vencidas</th><th>Atendidas</th><th>% en plazo</th><th>Días prom.</th><th>Trámites</th></tr></thead><tbody>
          ${d.por_area.map(a => `<tr><td><b>${esc(a.nombre)}</b></td><td>${esc(a.total)}</td><td>${esc(a.abiertas)}</td><td ${a.vencidas ? 'style="color:var(--c-danger);font-weight:700"' : ''}>${esc(a.vencidas)}</td><td>${esc(a.atendidas)}</td><td>${a.en_plazo_pct === null ? '—' : esc(a.en_plazo_pct) + ' %'}</td><td>${a.tiempo_promedio_dias === null ? '—' : esc(a.tiempo_promedio_dias)}</td><td>${esc(a.tramites)} <span class="hint">(${esc(a.tramites_en_evaluacion)} en curso)</span></td></tr>`).join('')}</tbody></table></div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6" style="margin-top:1.25rem">
            <div><div class="section-title">Solicitudes por tipo</div>${barras(sol.por_clase, { QUEJA: 'Quejas', RECLAMO: 'Reclamos', PETICION: 'Peticiones' })}
              <div class="section-title">Solicitudes por estado</div>${barras(sol.por_estado, ESTADOS_SOL_UI)}</div>
            <div><div class="section-title">Trámites por tipo</div>${barras(Object.fromEntries(d.tramites.por_tipo.map(t => [t.nombre, t.total])), {})}
              <div class="section-title">Trámites por estado</div>${barras(d.tramites.por_estado, {})}</div></div>`;
    } catch (err) {
        if (cuerpo.isConnected) cuerpo.innerHTML = `<p class="text-center py-8" style="color:var(--c-danger)">${esc(err.message)}</p>`;
    }
}

async function cargarAuditoria() {
    const cont = document.getElementById('au-lista');
    if (!cont) return;
    const qs = new URLSearchParams();
    const q = document.getElementById('au-q').value.trim(); const a = document.getElementById('au-accion').value;
    if (q) qs.set('q', q); if (a) qs.set('accion', a);
    try {
        const lista = await apiFetch(`/admin/auditoria?${qs}`, { method: 'GET', silent: true });
        if (!cont.isConnected) return;
        cont.innerHTML = lista.length ? `<div class="table-wrapper"><table class="table"><thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Sobre</th><th>Detalle</th></tr></thead><tbody>
          ${lista.map(e => `<tr><td style="white-space:nowrap">${esc(formatearFecha(e.fecha))}</td><td>${esc(e.usuario_nombre || '—')}<div class="hint">${esc(e.usuario_dni || '')}</div></td>
            <td><span class="audit-accion">${esc(e.accion)}</span></td><td>${esc(e.entidad_id || '')}</td><td style="max-width:22rem;word-break:break-word">${esc(e.detalle || '')}</td></tr>`).join('')}</tbody></table></div>`
            : vacio('fa-clipboard-list', 'No hay registros con esos filtros.');
    } catch (err) {
        if (cont.isConnected) cont.innerHTML = `<p class="text-center py-8" style="color:var(--c-danger)">${esc(err.message)}</p>`;
    }
}

// ===========================================
// REGISTRO Y RECUPERACIÓN DE CONTRASEÑA (pantalla de ingreso)
// ===========================================
function campoForm(id, label, tipo, extra = '') {
    return `<div class="form-group"><label for="${id}">${label}</label><input id="${id}" type="${tipo}" class="form-input" style="padding-right:.85rem" ${extra}></div>`;
}

function abrirRegistro() {
    const m = abrirModal(`<div class="modal-head"><h2>Crear cuenta</h2><div class="sub">Para hacer trámites, pagos y reclamos en línea</div></div>
      <div class="modal-body"><form id="rg-form" novalidate>
        ${campoForm('rg-dni', 'DNI', 'text', 'inputmode="numeric" maxlength="8" autocomplete="username"')}
        ${campoForm('rg-nombre', 'Nombres y apellidos completos', 'text', 'maxlength="255" autocomplete="name"')}
        ${campoForm('rg-email', 'Correo electrónico', 'email', 'maxlength="100" autocomplete="email"')}
        <div class="hint" style="margin:-.5rem 0 .8rem">Lo usaremos para avisarte de tus trámites y para recuperar tu contraseña.</div>
        ${campoForm('rg-telefono', 'Celular (opcional)', 'tel', 'inputmode="tel" maxlength="15" autocomplete="tel"')}
        ${campoForm('rg-clave', 'Contraseña (mínimo 8 caracteres)', 'password', 'autocomplete="new-password"')}
        ${campoForm('rg-clave2', 'Repite la contraseña', 'password', 'autocomplete="new-password"')}
        <div id="rg-error" class="pay-alert hidden"></div>
        <button class="btn btn-primario w-full" id="rg-enviar" type="submit">Crear mi cuenta</button></form></div>`);
    const f = m.el.querySelector('#rg-form');
    f.addEventListener('submit', async (e) => {
        e.preventDefault();
        const err = f.querySelector('#rg-error'); const fallo = (t) => { err.textContent = t; err.classList.remove('hidden'); };
        err.classList.add('hidden');
        const v = (id) => f.querySelector('#' + id).value.trim();
        if (!/^\d{8}$/.test(v('rg-dni'))) return fallo('El DNI debe tener 8 dígitos.');
        if (v('rg-nombre').length < 3) return fallo('Ingresa tu nombre completo.');
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v('rg-email'))) return fallo('Ingresa un correo válido.');
        if (f.querySelector('#rg-clave').value.length < 8) return fallo('La contraseña debe tener al menos 8 caracteres.');
        if (f.querySelector('#rg-clave').value !== f.querySelector('#rg-clave2').value) return fallo('Las contraseñas no coinciden.');
        const btn = f.querySelector('#rg-enviar'); btn.disabled = true;
        try {
            const data = await apiFetch('/auth/registro', { method: 'POST', silent: true, body: JSON.stringify({
                dni: v('rg-dni'), nombre: v('rg-nombre'), email: v('rg-email'), telefono: v('rg-telefono') || null, password: f.querySelector('#rg-clave').value }) });
            m.cerrar();
            localStorage.setItem('token', data.access_token);
            localStorage.setItem('user', JSON.stringify(data.user));
            appState.currentUser = data.user;
            showDashboard(data.user);
        } catch (e2) { fallo(e2.message); btn.disabled = false; }
    });
}

function abrirRecuperar() {
    const m = abrirModal(`<div class="modal-head"><h2>Recuperar contraseña</h2><div class="sub">Te enviaremos un código a tu correo registrado</div></div>
      <div class="modal-body">
        <form id="rc-paso1" novalidate>${campoForm('rc-dni', 'Tu DNI', 'text', 'inputmode="numeric" maxlength="8"')}
          <div id="rc-error1" class="pay-alert hidden"></div>
          <button class="btn btn-primario w-full" type="submit">Enviar código</button></form>
        <form id="rc-paso2" class="hidden" novalidate><div class="pay-hint" id="rc-aviso" style="margin-bottom:.9rem"></div>
          ${campoForm('rc-codigo', 'Código de 6 dígitos', 'text', 'inputmode="numeric" maxlength="6" autocomplete="one-time-code"')}
          ${campoForm('rc-clave', 'Nueva contraseña (mínimo 8 caracteres)', 'password', 'autocomplete="new-password"')}
          <div id="rc-error2" class="pay-alert hidden"></div>
          <button class="btn btn-primario w-full" type="submit">Cambiar contraseña</button></form></div>`);
    const p1 = m.el.querySelector('#rc-paso1'), p2 = m.el.querySelector('#rc-paso2');
    const mostrar = (id, t) => { const e = m.el.querySelector(id); e.textContent = t; e.classList.remove('hidden'); };
    p1.addEventListener('submit', async (e) => {
        e.preventDefault(); m.el.querySelector('#rc-error1').classList.add('hidden');
        const dni = p1.querySelector('#rc-dni').value.trim();
        if (!/^\d{8}$/.test(dni)) return mostrar('#rc-error1', 'El DNI debe tener 8 dígitos.');
        try {
            const r = await apiFetch('/auth/olvide-clave', { method: 'POST', silent: true, body: JSON.stringify({ dni }) });
            p1.classList.add('hidden'); p2.classList.remove('hidden');
            m.el.querySelector('#rc-aviso').textContent = r.message;
            p2.dataset.dni = dni; p2.querySelector('#rc-codigo').focus();
        } catch (e2) { mostrar('#rc-error1', e2.message); }
    });
    p2.addEventListener('submit', async (e) => {
        e.preventDefault(); m.el.querySelector('#rc-error2').classList.add('hidden');
        const codigo = p2.querySelector('#rc-codigo').value.trim(), nueva = p2.querySelector('#rc-clave').value;
        if (!/^\d{6}$/.test(codigo)) return mostrar('#rc-error2', 'El código tiene 6 dígitos.');
        if (nueva.length < 8) return mostrar('#rc-error2', 'La contraseña debe tener al menos 8 caracteres.');
        try {
            await apiFetch('/auth/restablecer-clave', { method: 'POST', silent: true, body: JSON.stringify({ dni: p2.dataset.dni, codigo, nueva_clave: nueva }) });
            m.cerrar();
            const inp = document.getElementById('login-dni'); if (inp) inp.value = p2.dataset.dni;
            showAlert('Contraseña actualizada', 'Ya puedes ingresar con tu nueva contraseña.', 'success');
        } catch (e2) { mostrar('#rc-error2', e2.message); }
    });
}

document.addEventListener('click', (e) => {
    if (e.target.closest('#link-registro')) abrirRegistro();
    else if (e.target.closest('#link-recuperar')) abrirRecuperar();
});
