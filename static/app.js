// ===========================================
// APP.JS v2.5 - MEJORADO Y OPTIMIZADO
// ===========================================

// --- Selectores Globales ---
const API_BASE_URL = "/api/v1";
const loginPage = document.getElementById('login-page');
const dashboardContainer = document.getElementById('dashboard-container');
const dashboardTabs = document.getElementById('dashboard-tabs');
const dashboardContent = document.getElementById('dashboard-content');
const userName = document.getElementById('user-name');
const logoutButton = document.getElementById('logout-button');
const loader = document.getElementById('loader');
const loginForm = document.getElementById('login-form');
const loginDni = document.getElementById('login-dni');
const loginPassword = document.getElementById('login-password');

// --- Estados Globales ---
const appState = {
    currentUser: null,
    currentTab: null,
    ntState: { tramite: null },
    mdState: { deudas: [], deudaSeleccionada: null }
};

// ===========================================
// FUNCIONES DE UTILIDAD MEJORADAS
// ===========================================

function showLoader(show) {
    if (loader) {
        loader.classList.toggle('hidden', !show);
    }
}

function showAlert(title, text, icon = 'info', timer = 3000) {
    return Swal.fire({
        title,
        text,
        icon,
        timer,
        timerProgressBar: true,
        showConfirmButton: false,
        toast: true,
        position: 'top-end'
    });
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
const esc = escapeHtml;

function showConfirmAlert(title, text, icon = 'question') {
    return Swal.fire({
        title,
        text,
        icon,
        showCancelButton: true,
        confirmButtonText: 'Sí',
        cancelButtonText: 'No'
    });
}

async function apiFetch(endpoint, options = {}) {
    const { silent, ...fetchOptions } = options;  // silent: sin loader global ni alerta (lo maneja quien llama)
    if (!silent) showLoader(true);
    const token = localStorage.getItem('token');
    const headers = {
        'Accept': 'application/json',
        ...options.headers
    };
    
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    
    if (!(options.body instanceof FormData) && !(options.body instanceof URLSearchParams)) {
        headers['Content-Type'] = 'application/json';
    }

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, { 
            ...fetchOptions, 
            headers,
            signal: AbortSignal.timeout(30000) // Timeout de 30 segundos
        });
        
        if (response.status === 401 && token && endpoint !== '/auth/login') {
            // Sesión vencida o token inválido: volver al login
            localStorage.removeItem('token');
            localStorage.removeItem('user');
            window.location.reload();
            throw new Error('Su sesión ha expirado. Inicie sesión nuevamente.');
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            let detalle = errorData.detail;
            if (Array.isArray(detalle)) {  // errores de validación (422): se muestran los mensajes legibles
                detalle = detalle.map(d => String(d.msg || '').replace(/^Value error, /, '')).filter(Boolean).join(' ');
            }
            const errorMsg = (typeof detalle === 'string' && detalle) || errorData.error || `Error ${response.status}: ${response.statusText}`;
            const err = new Error(errorMsg);
            err.status = response.status;
            throw err;
        }
        
        return await response.json();
    } catch (error) {
        if (!silent) {
            console.error('Error en apiFetch:', error);
            if (error.name === 'AbortError') {
                showAlert('Error', 'La solicitud tardó demasiado tiempo. Intente nuevamente.', 'error');
            } else {
                showAlert('Error', error.message, 'error');
            }
        } else if (error.name === 'AbortError') {
            error.message = 'La solicitud tardó demasiado tiempo. Verifique su conexión.';
        }
        throw error;
    } finally {
        if (!silent) showLoader(false);
    }
}

async function apiFetchFile(endpoint, filename) {
    showLoader(true);
    const token = localStorage.getItem('token');
    
    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            method: 'GET',
            headers: { 
                'Authorization': `Bearer ${token}`,
                'Cache-Control': 'no-cache'
            }
        });
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const errorMsg = errorData.detail || 'Error al descargar el archivo.';
            throw new Error(errorMsg);
        }
        
        const blob = await response.blob();
        
        // Verificar que el blob no esté vacío
        if (blob.size === 0) {
            throw new Error('El archivo está vacío');
        }
        
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        
        // Limpiar después de la descarga
        setTimeout(() => {
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        }, 100);
        
        showAlert('¡Descarga exitosa!', `Archivo ${filename} descargado`, 'success');
    } catch (error) {
        console.error('Error en apiFetchFile:', error);
        showAlert('Error', error.message, 'error');
        throw error;
    } finally {
        showLoader(false);
    }
}

function formatCurrency(amount) {
    if (typeof amount !== 'number') {
        amount = parseFloat(amount) || 0;
    }
    return amount.toLocaleString('es-PE', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

function validateDNI(dni) {
    return /^\d{8}$/.test(dni);
}

function validateEmail(email) {
    if (!email) return true; // Email opcional
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

// ===========================================
// AUTENTICACIÓN MEJORADA
// ===========================================

async function handleLogin(e) {
    e.preventDefault();
    
    const dni = loginDni.value.trim();
    const password = loginPassword.value.trim();
    
    // Validaciones del lado del cliente
    if (!dni || !password) {
        showAlert('Error', 'Por favor complete todos los campos.', 'warning');
        return;
    }
    
    if (!validateDNI(dni)) {
        showAlert('Error', 'El DNI debe tener 8 dígitos numéricos.', 'warning');
        return;
    }
    
    const formData = new URLSearchParams();
    formData.append('username', dni);
    formData.append('password', password);
    
    try {
        const data = await apiFetch('/auth/login', {
            method: 'POST',
            body: formData,
            headers: {'Content-Type': 'application/x-www-form-urlencoded'}
        });
        
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('user', JSON.stringify(data.user));
        appState.currentUser = data.user;
        
        await showAlert(`¡Bienvenido, ${data.user.name.split(' ')[0]}!`, 'Has ingresado al portal municipal.', 'success', 2000);
        
        showDashboard(data.user);
    } catch (error) {
        // El error ya fue manejado en apiFetch
        console.log("Fallo de login:", error);
    }
}

function handleLogout() {
    showConfirmAlert('Cerrar Sesión', '¿Está seguro que desea cerrar sesión?', 'question')
        .then((result) => {
            if (result.isConfirmed) {
                localStorage.removeItem('token');
                localStorage.removeItem('user');
                appState.currentUser = null;
                loginPage.classList.remove('hidden');
                dashboardContainer.classList.add('hidden');
                dashboardTabs.innerHTML = '';
                dashboardContent.innerHTML = '';
                
                // Limpiar formularios
                if (loginForm) loginForm.reset();
            }
        });
}

function renderBienvenida(user) {
    const el = document.getElementById('welcome');
    if (!el) return;
    const h = new Date().getHours();
    const saludo = h < 12 ? 'Buenos días' : (h < 19 ? 'Buenas tardes' : 'Buenas noches');
    const fecha = new Date().toLocaleDateString('es-PE', { weekday: 'long', day: 'numeric', month: 'long' });
    const nombre = (user.name || '').split(' ')[0];
    const areas = (typeof AREAS_UI !== 'undefined') ? AREAS_UI : {};
    const rol = user.role === 'admin' ? 'Administración municipal'
        : user.role === 'funcionario' ? (areas[user.area] || 'Funcionario municipal') : 'Portal del vecino';
    const accesos = user.role === 'ciudadano' ? [
        ['mis-deudas', 'fa-credit-card', 'Pagar deudas'],
        ['nuevo-tramite', 'fa-file-alt', 'Nuevo trámite'],
        ['solicitudes', 'fa-comments', 'Queja o reclamo'],
    ] : [];
    el.innerHTML = `
        <div>
            <div class="welcome-rol">${esc(rol)}</div>
            <h2>${saludo}, ${esc(nombre.charAt(0) + nombre.slice(1).toLowerCase())}</h2>
            <p>${esc(fecha.charAt(0).toUpperCase() + fecha.slice(1))}</p>
        </div>
        <div class="welcome-actions">${accesos.map(a => `<button type="button" class="welcome-btn" data-ir="${a[0]}"><i class="fas ${a[1]}"></i>${a[2]}</button>`).join('')}</div>`;
    el.classList.remove('hidden');
    el.querySelectorAll('[data-ir]').forEach(b => b.addEventListener('click', () => loadTabContent(b.dataset.ir, user.role)));
}

function showDashboard(user) {
    if (!user) return;
    
    appState.currentUser = user;
    userName.textContent = user.name.split(' ')[0];
    const avatar = document.getElementById('user-avatar');
    if (avatar) avatar.textContent = (user.name || '?').trim().charAt(0).toUpperCase();
    loginPage.classList.add('hidden');
    dashboardContainer.classList.remove('hidden');
    renderBienvenida(user);
    generateTabs(user.role);
    if (typeof iniciarNotificaciones === 'function') iniciarNotificaciones();
}

// ===========================================
// NAVEGACIÓN DEL DASHBOARD MEJORADA
// ===========================================

const TABS = {
    ciudadano: [
        { id: 'nuevo-tramite', icon: 'fa-file-alt', label: 'Nuevo Trámite' },
        { id: 'mis-tramites', icon: 'fa-folder-open', label: 'Mis Trámites' },
        { id: 'solicitudes', icon: 'fa-comments', label: 'Quejas y Peticiones' },
        { id: 'mis-deudas', icon: 'fa-search-dollar', label: 'Mis Deudas' },
        { id: 'mis-pagos', icon: 'fa-receipt', label: 'Mis Pagos' },
        { id: 'asistente-ia', icon: 'fa-robot', label: 'Asistente IA' },
    ],
    funcionario: [
        { id: 'solicitudes', icon: 'fa-comments', label: 'Quejas y Peticiones' },
        { id: 'revision-tramites', icon: 'fa-check-double', label: 'Revisión de Trámites' },
    ],
    admin: [
        { id: 'general', icon: 'fa-chart-line', label: 'Dashboard General' },
        { id: 'revision-tramites', icon: 'fa-check-double', label: 'Revisión de Trámites' },
        { id: 'solicitudes', icon: 'fa-comments', label: 'Quejas y Peticiones' },
        { id: 'recaudacion', icon: 'fa-coins', label: 'Recaudación' },
        { id: 'reportes', icon: 'fa-chart-bar', label: 'Reportes y Auditoría' },
        { id: 'gestion-usuarios', icon: 'fa-users', label: 'Gestión de Usuarios' },
        { id: 'metricas-ia', icon: 'fa-brain', label: 'Métricas IA' },
    ]
};

function generateTabs(role) {
    const tabsForRole = TABS[role] || TABS.ciudadano;
    dashboardTabs.innerHTML = '';
    
    tabsForRole.forEach((tab, index) => {
        const link = document.createElement('a');
        link.href = '#';
        link.id = `tab-link-${tab.id}`;
        link.className = 'dashboard-tab-link';
        link.dataset.tab = tab.id;
        link.innerHTML = `<i class="fas ${tab.icon}"></i> ${tab.label}`;
        link.addEventListener('click', (e) => {
            e.preventDefault();
            loadTabContent(tab.id, role);
        });
        dashboardTabs.appendChild(link);
        
        // Cargar la primera pestaña por defecto
        if (index === 0) {
            loadTabContent(tab.id, role);
        }
    });
}

function loadTabContent(tabId, role) {
    // Actualizar estado y UI
    appState.currentTab = tabId;
    
    document.querySelectorAll('.dashboard-tab-link').forEach(link => {
        link.classList.toggle('active', link.dataset.tab === tabId);
    });
    
    // Mostrar loading state
    dashboardContent.innerHTML = '<div class="card"><div class="flex justify-center items-center py-8"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div><span class="ml-3">Cargando...</span></div></div>';
    
    // Cargar contenido después de un pequeño delay para mejor UX
    setTimeout(() => {
        try {
            if (role === 'ciudadano') {
                loadCiudadanoTab(tabId);
            } else if (role === 'admin' || role === 'funcionario') {
                loadAdminTab(tabId);
            }
        } catch (error) {
            console.error('Error cargando pestaña:', error);
            dashboardContent.innerHTML = `
                <div class="card">
                    <div class="text-red-500 text-center py-8">
                        <i class="fas fa-exclamation-triangle text-4xl mb-4"></i>
                        <p>Error al cargar el contenido. Intente nuevamente.</p>
                    </div>
                </div>`;
        }
    }, 100);
}

function loadCiudadanoTab(tabId) {
    switch(tabId) {
        case 'nuevo-tramite':
            dashboardContent.innerHTML = RENDER.nuevoTramite();
            initNuevoTramiteListeners();
            break;
        case 'mis-tramites':
            dashboardContent.innerHTML = RENDER.misTramites();
            initMisTramitesListeners();
            break;
        case 'solicitudes':
            renderMisSolicitudes();
            break;
        case 'mis-deudas':
            dashboardContent.innerHTML = RENDER.misDeudas();
            initMisDeudasListeners();
            break;
        case 'mis-pagos':
            renderMisPagos();
            break;
        case 'asistente-ia':
            dashboardContent.innerHTML = RENDER.asistenteIA();
            initAsistenteIAListeners();
            break;
        default:
            dashboardContent.innerHTML = RENDER.errorTab('Pestaña no encontrada');
    }
}

function loadAdminTab(tabId) {
    switch(tabId) {
        case 'general':
            dashboardContent.innerHTML = RENDER.adminGeneral();
            initAdminGeneralListeners();
            break;
        case 'revision-tramites':
            dashboardContent.innerHTML = RENDER.adminRevisionTramitesLoading();
            loadAdminTramites();
            break;
        case 'solicitudes':
            renderAdminSolicitudes();
            break;
        case 'recaudacion':
            renderRecaudacion();
            break;
        case 'gestion-usuarios':
            dashboardContent.innerHTML = RENDER.adminGestionUsuarios();
            initGestionUsuariosListeners();
            break;
        case 'reportes':
            renderReportes();
            break;
        case 'metricas-ia':
            dashboardContent.innerHTML = RENDER.adminMetricasIA();
            initMetricasIAListeners();
            break;
        default:
            dashboardContent.innerHTML = RENDER.errorTab('Pestaña no encontrada');
    }
}

// ===========================================
// RENDERIZADO DE HTML MEJORADO
// ===========================================

const RENDER = {
    // --- Mensajes de error y estados ---
    errorTab: (message) => `
        <div class="card">
            <div class="text-red-500 text-center py-8">
                <i class="fas fa-exclamation-triangle text-4xl mb-4"></i>
                <p>${esc(message)}</p>
            </div>
        </div>`,

    loadingState: () => `
        <div class="flex justify-center items-center py-8">
            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            <span class="ml-3">Cargando...</span>
        </div>`,

    // --- Ciudadano ---
    nuevoTramite: () => `
        <div class="card">
            <h2 class="card-header">Iniciar Nuevo Trámite</h2>
            <div id="nt-step-1" class="mb-8">
                <h3 class="step-header">Paso 1: Seleccione el trámite</h3>
                <div class="form-group">
                    <label for="nt-tipo-tramite">Tipo de Trámite</label>
                    <select id="nt-tipo-tramite" class="form-select max-w-lg">
                        <option value="">Cargando catálogo...</option>
                    </select>
                </div>
                <div id="nt-info" class="catalog-info hidden"></div>
                <div id="nt-campos"></div>
                <button id="nt-btn-step1" class="btn btn-primario">
                    Siguiente <i class="fas fa-arrow-right ml-2"></i>
                </button>
            </div>
            
            <div id="nt-step-2" class="mb-8 hidden">
                <h3 class="step-header">Paso 2: Adjuntar Documentos</h3>
                <form id="nt-form-upload" class="p-4 border-2 border-dashed border-gray-300 rounded-lg">
                    <label for="nt-file-upload" class="block text-sm font-medium text-gray-600 mb-2">
                        Subir archivos (PDF, JPG, PNG) - Máx. 10MB por archivo
                    </label>
                    <input type="file" id="nt-file-upload" name="files" multiple 
                           accept=".pdf,.jpg,.jpeg,.png"
                           class="w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"/>
                    <div id="nt-file-list" class="mt-3 text-sm text-gray-600"></div>
                    <div id="nt-file-errors" class="mt-2 text-sm text-red-600 hidden"></div>
                    <button type="submit" id="nt-btn-step2" class="btn btn-primario mt-4">
                        Confirmar y Ver Pago <i class="fas fa-arrow-right ml-2"></i>
                    </button>
                </form>
            </div>
            
            <div id="nt-step-3" class="mb-8 hidden">
                <h3 class="step-header">Paso 3: Realizar Pago</h3>
                <div class="bg-gray-50 p-4 rounded-lg shadow-sm max-w-lg">
                    <h4 class="text-lg font-medium text-gray-700">Resumen de Pago</h4>
                    <p class="mt-2">Trámite: <strong id="nt-resumen-tipo"></strong></p>
                    <p class="mt-1">Expediente: <strong id="nt-resumen-expediente"></strong></p>
                    <p class="mt-3 text-2xl font-bold text-gray-900">Total: S/ <span id="nt-resumen-costo">0.00</span></p>
                </div>
                <button type="button" id="nt-btn-step3" class="btn btn-exito mt-4" style="font-size:1.05rem;padding:.85rem 1.5rem">
                    <i class="fas fa-lock"></i> Pagar ahora
                </button>
            </div>
        </div>`,

    misTramites: () => `
        <div class="card">
            <h2 class="card-header">Consulta de Trámites</h2>
            <form id="mt-form-consulta" class="flex flex-col sm:flex-row gap-4 mb-6">
                <input type="text" id="mt-input-expediente" placeholder="Ingrese Nro de Expediente" class="form-input flex-grow">
                <button type="submit" class="btn btn-primario">
                    <i class="fas fa-search"></i> Consultar
                </button>
            </form>
            <div id="mt-resultado"></div>
        </div>`,

    misDeudas: () => `
        <div class="card">
            <h2 class="card-header">Consulta y Pago de Deudas</h2>
            <div id="md-resultado-deudas">${RENDER.loadingState()}</div>
            <div id="md-form-pago-container" class="hidden">
                <hr class="my-6">
                <h3 class="text-xl font-semibold text-gray-800">Pagar Deuda</h3>
                <div class="pay-box">
                    <p>Deuda: <strong id="md-deuda-tipo"></strong></p>
                    <p>Periodo: <strong id="md-deuda-periodo"></strong></p>
                    <div id="md-deuda-desglose" style="font-size:.88rem;color:var(--c-muted)"></div>
                    <div class="pay-box-total"><span>Total a pagar</span><strong>S/ <span id="md-deuda-monto">0.00</span></strong></div>
                </div>
                <button type="button" id="md-btn-pagar" class="btn btn-exito mt-4" style="font-size:1.05rem;padding:.85rem 1.5rem">
                    <i class="fas fa-lock"></i> Pagar ahora
                </button>
            </div>
        </div>`,

    asistenteIA: () => `
        <div class="card">
            <h2 class="card-header">Asistente Virtual (HU-028)</h2>
            <div class="chat-container">
                <div class="chat-log" id="ai-chat-log">
                    <div class="chat-message ai">
                        <div class="chat-bubble">¡Hola! Soy Muni-Asistente. ¿En qué puedo ayudarte hoy? Puedo responder preguntas sobre trámites municipales, requisitos, costos y más.</div>
                    </div>
                </div>
                <form class="chat-input-form" id="ai-chat-form">
                    <input type="text" id="ai-chat-input" placeholder="Escribe tu consulta aquí..." class="form-input" maxlength="500">
                    <button type="submit" class="btn btn-primario">
                        <i class="fas fa-paper-plane"></i>
                    </button>
                </form>
            </div>
        </div>`,

    // --- Admin ---
    adminGeneral: () => `
        <div class="card">
            <h2 class="card-header">Dashboard General</h2>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div class="card">
                    <h3 class="text-lg font-semibold text-gray-700">Trámites Ingresados (Hoy)</h3>
                    <p class="text-4xl font-bold text-blue-600 mt-2" id="admin-tramites-hoy">--</p>
                </div>
                <div class="card">
                    <h3 class="text-lg font-semibold text-gray-700">Trámites Pendientes</h3>
                    <p class="text-4xl font-bold text-yellow-500 mt-2" id="admin-tramites-pendientes">--</p>
                </div>
                <div class="card">
                    <h3 class="text-lg font-semibold text-gray-700">Recaudación del Día</h3>
                    <p class="text-4xl font-bold text-green-600 mt-2" id="admin-recaudacion-hoy">--</p>
                </div>
            </div>
        </div>`,

    adminRevisionTramitesLoading: () => `
        <div class="card">
            <h2 class="card-header">Gestor de Trámites (HU-005)</h2>
            ${RENDER.loadingState()}
        </div>`,

    adminMetricasIA: () => `
        <div class="card">
            <h2 class="card-header">Métricas de IA</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div class="card">
                    <h3 class="text-lg font-semibold text-gray-700">Consultas del Día</h3>
                    <p class="text-4xl font-bold text-purple-600 mt-2" id="metricas-consultas-dia">--</p>
                </div>
                <div class="card">
                    <h3 class="text-lg font-semibold text-gray-700">Satisfacción Usuarios</h3>
                    <p class="text-4xl font-bold text-green-600 mt-2" id="metricas-satisfaccion">--%</p>
                </div>
            </div>
        </div>`,

    adminGestionUsuarios: () => `
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div class="lg:col-span-1">
                <div class="card">
                    <h2 class="card-header">Registrar Ciudadano</h2>
                    <form id="admin-create-user-form">
                        <div class="form-group">
                            <label for="admin-user-dni">DNI</label>
                            <input type="text" id="admin-user-dni" class="form-input" maxlength="8" required>
                            <div class="text-sm text-red-600 hidden" id="admin-dni-error"></div>
                        </div>
                        <div class="form-group">
                            <label for="admin-user-nombre">Nombre Completo</label>
                            <input type="text" id="admin-user-nombre" class="form-input" required>
                        </div>
                        <div class="form-group">
                            <label for="admin-user-email">Email (Opcional)</label>
                            <input type="email" id="admin-user-email" class="form-input">
                            <div class="text-sm text-red-600 hidden" id="admin-email-error"></div>
                        </div>
                        <div class="form-group">
                            <label for="admin-user-password">Contraseña Temporal</label>
                            <input type="password" id="admin-user-password" class="form-input" minlength="8" required>
                        </div>
                        <div class="form-group">
                            <label for="admin-user-role">Rol</label>
                            <select id="admin-user-role" class="form-select">
                                <option value="ciudadano">Ciudadano</option>
                                <option value="funcionario">Funcionario de un área</option>
                                <option value="admin">Administrador</option>
                            </select>
                        </div>
                        <div class="form-group hidden" id="admin-user-area-group">
                            <label for="admin-user-area">Área del funcionario</label>
                            <select id="admin-user-area" class="form-select">
                                ${Object.entries(AREAS_UI).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}
                            </select>
                        </div>
                        <button type="submit" class="btn btn-primario w-full">
                            <i class="fas fa-plus-circle"></i> Registrar Usuario
                        </button>
                    </form>
                </div>
            </div>
            
            <div class="lg:col-span-2">
                <div class="card">
                    <div class="flex justify-between items-center mb-6">
                        <h2 class="card-header" style="margin-bottom: 0; border: none;">Lista de Usuarios</h2>
                        <button id="btn-export-sql" class="btn btn-exito">
                            <i class="fas fa-database"></i> Exportar a SQL
                        </button>
                    </div>
                    <div class="table-wrapper">
                        <table class="table">
                            <thead>
                                <tr>
                                    <th>DNI</th>
                                    <th>Nombre</th>
                                    <th>Email</th>
                                    <th>Rol</th>
                                    <th>Acciones</th>
                                </tr>
                            </thead>
                            <tbody id="admin-user-list-body">
                                <tr><td colspan="5">${RENDER.loadingState()}</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>`,

    adminRenderTablaTramites: (tramites) => {
        const lista = tramites ?? [];
        const rows = lista.map(tramite => `
            <tr>
                <td class="font-mono">${esc(tramite.expediente)}</td>
                <td>${esc(tramite.ciudadano_nombre)} (${esc(tramite.ciudadano_dni)})</td>
                <td>${esc(nombreTramite(tramite.tipo))}</td>
                <td>${new Date(tramite.fecha_creacion).toLocaleDateString()}</td>
                <td><span class="status-badge status-${esc(tramite.estado)}">${esc(tramite.estado.replace(/_/g, ' '))}</span></td>
                <td>S/ ${formatCurrency(tramite.costo_total)}</td>
                <td>
                    <button class="btn btn-primario btn-revisar-tramite" data-tramite-id="${tramite.id}" style="padding: 5px 10px; font-size: 14px;">
                        <i class="fas fa-eye"></i> Revisar
                    </button>
                </td>
            </tr>`).join('');
        
        return `
            <div class="card">
                <h2 class="card-header">Gestor de Trámites (HU-005)</h2>
                <div class="mb-4 flex justify-between items-center">
                    <p class="text-gray-600">Total de trámites: <strong>${lista.length}</strong></p>
                    <button id="btn-refresh-tramites" class="btn btn-secundario">
                        <i class="fas fa-sync-alt"></i> Actualizar
                    </button>
                </div>
                <div class="table-wrapper">
                    <table class="table">
                        <thead>
                            <tr>
                                <th>Expediente</th>
                                <th>Ciudadano (DNI)</th>
                                <th>Tipo</th>
                                <th>Fecha</th>
                                <th>Estado</th>
                                <th>Costo</th>
                                <th>Acciones</th>
                            </tr>
                        </thead>
                        <tbody>${rows || '<tr><td colspan="7" class="text-center py-8 text-gray-500">No hay trámites para revisar. ¡Buen trabajo!</td></tr>'}</tbody>
                    </table>
                </div>
            </div>`;
    }
};

// ===========================================
// LÓGICA: NUEVO TRÁMITE (MEJORADA)
// ===========================================

function initNuevoTramiteListeners() {
    initCatalogoTramites();
    // Paso 1: Selección de trámite
    document.getElementById('nt-btn-step1').addEventListener('click', handleStep1);
    
    // Validación de archivos
    document.getElementById('nt-file-upload').addEventListener('change', handleFileValidation);
    
    // Paso 2: Subida de documentos
    document.getElementById('nt-form-upload').addEventListener('submit', handleStep2);
    
    // Paso 3: Pago
    document.getElementById('nt-btn-step3').addEventListener('click', handleStep3);
}

async function handleStep1() {
    const tipoSelect = document.getElementById('nt-tipo-tramite');
    const tipo = tipoSelect.value;
    
    if (!tipo) {
        showAlert('Error', 'Debe seleccionar un tipo de trámite.', 'warning');
        tipoSelect.focus();
        return;
    }
    
    const detalles = leerCamposTramite();
    if (detalles === null) return;

    try {
        const tramite = await apiFetch('/tramites/', {
            method: 'POST',
            body: JSON.stringify({ tipo: tipo, detalles: detalles })
        });
        
        appState.ntState.tramite = tramite;
        
        // Transición suave entre pasos
        document.getElementById('nt-step-1').classList.add('hidden');
        setTimeout(() => {
            document.getElementById('nt-step-2').classList.remove('hidden');
        }, 300);
    } catch (error) {
        console.error('Error al crear trámite:', error);
    }
}

function handleFileValidation() {
    const fileInput = document.getElementById('nt-file-upload');
    const fileListDiv = document.getElementById('nt-file-list');
    const errorDiv = document.getElementById('nt-file-errors');
    const maxSize = 10 * 1024 * 1024; // 10MB
    
    fileListDiv.innerHTML = '';
    errorDiv.classList.add('hidden');
    errorDiv.innerHTML = '';
    
    if (fileInput.files.length === 0) return;
    
    const validFiles = [];
    const invalidFiles = [];
    
    Array.from(fileInput.files).forEach(file => {
        if (file.size > maxSize) {
            invalidFiles.push(`${file.name} (tamaño excedido)`);
        } else if (!file.type.match(/(pdf|image\/(jpeg|png))/)) {
            invalidFiles.push(`${file.name} (formato no válido)`);
        } else {
            validFiles.push(file);
        }
    });
    
    if (validFiles.length > 0) {
        fileListDiv.innerHTML = `<strong>Archivos válidos (${validFiles.length}):</strong><br>${validFiles.map(f => f.name).join('<br>')}`;
    }
    
    if (invalidFiles.length > 0) {
        errorDiv.classList.remove('hidden');
        errorDiv.innerHTML = `<strong>Archivos rechazados:</strong><br>${invalidFiles.join('<br>')}`;
    }
}

async function handleStep2(e) {
    e.preventDefault();
    const fileInput = document.getElementById('nt-file-upload');
    const files = fileInput.files;
    
    if (files.length === 0) {
        showAlert('Error', 'Debe seleccionar al menos un archivo válido.', 'warning');
        return;
    }
    
    // Verificar si hay archivos inválidos
    const errorDiv = document.getElementById('nt-file-errors');
    if (!errorDiv.classList.contains('hidden')) {
        showAlert('Error', 'Corrija los archivos inválidos antes de continuar.', 'warning');
        return;
    }
    
    const formData = new FormData();
    Array.from(files).forEach(file => {
        formData.append('files', file);
    });
    
    try {
        const tramite_id = appState.ntState.tramite.id;
        const tramite = await apiFetch(`/tramites/${tramite_id}/upload-documentos`, {
            method: 'POST',
            body: formData
        });
        
        appState.ntState.tramite = tramite;
        
        // Actualizar resumen
        document.getElementById('nt-resumen-tipo').textContent = nombreTramite(tramite.tipo);
        document.getElementById('nt-resumen-expediente').textContent = tramite.expediente;
        document.getElementById('nt-resumen-costo').textContent = formatCurrency(tramite.costo_total);
        
        // Transición al paso 3
        document.getElementById('nt-step-2').classList.add('hidden');
        setTimeout(() => {
            document.getElementById('nt-step-3').classList.remove('hidden');
        }, 300);
    } catch (error) {
        console.error('Error al subir documentos:', error);
    }
}

async function handleStep3() {
    const tramite = appState.ntState.tramite;
    if (!tramite) return;
    openPaymentModal({
        titulo: 'Pago de trámite',
        concepto: nombreTramite(tramite.tipo),
        referencia: `Exp. ${tramite.expediente}`,
        monto: String(tramite.costo_total),
        endpoint: `/pagos/tramite/${tramite.id}`,
        onClose: (pago) => {
            if (pago) {
                appState.ntState = { tramite: null };
                loadTabContent('mis-tramites', 'ciudadano');  // ya está en evaluación
            }
        }
    });
}

// ===========================================
// LÓGICA: MIS TRÁMITES (MEJORADA)
// ===========================================

function initMisTramitesListeners() {
    document.getElementById('mt-form-consulta').addEventListener('submit', handleConsultaTramite);
    
    // Consultar trámites recientes al cargar
    setTimeout(() => {
        loadTramitesRecientes();
    }, 500);
}

async function handleConsultaTramite(e) {
    e.preventDefault();
    const expediente = document.getElementById('mt-input-expediente').value.trim();
    const resultadoDiv = document.getElementById('mt-resultado');
    
    if (!expediente) {
        showAlert('Error', 'Ingrese un número de expediente.', 'warning');
        return;
    }
    
    resultadoDiv.dataset.manual = '1';  // evita que la lista de recientes (carga tardía) pise este resultado
    resultadoDiv.innerHTML = RENDER.loadingState();
    
    try {
        const tramite = await apiFetch(`/tramites/expediente/${encodeURIComponent(expediente)}`, {
            method: 'GET'
        });
        
        resultadoDiv.innerHTML = renderTramiteDetail(tramite);
        cargarSeguimientoTramite(resultadoDiv);
    } catch (error) {
        resultadoDiv.innerHTML = `
            <div class="text-center py-8 text-red-500">
                <i class="fas fa-exclamation-circle text-4xl mb-4"></i>
                <p>No se encontró el trámite con expediente: ${esc(expediente)}</p>
            </div>`;
    }
}

function renderObservaciones(observaciones) {
    if (!observaciones || observaciones.length === 0) return '';
    return `<ul class="border rounded-lg divide-y text-sm">${observaciones.map(o => `
        <li class="p-2">
            <span class="text-gray-500">${esc(o.fecha)} · ${esc(o.autor)} · ${esc(String(o.estado).replace(/_/g, ' '))}</span><br>
            ${esc(o.texto)}
        </li>`).join('')}</ul>`;
}

// Descarga de documentos con el token del usuario (los enlaces directos no llevan Authorization)
document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-doc-download');
    if (!btn) return;
    const endpoint = btn.dataset.url.replace(API_BASE_URL, '');
    apiFetchFile(endpoint, btn.dataset.nombre || 'documento').catch(err => showAlert('Error', err.message, 'error'));
});

function renderTramiteDetail(tramite) {
    const documentosHTML = tramite.documentos && tramite.documentos.length > 0
        ? tramite.documentos.map(doc => `
            <li class="flex items-center justify-between py-2 border-b">
                <span class="truncate flex-1">${esc(doc.nombre)}</span>
                <button type="button" class="btn btn-secundario ml-2 btn-doc-download" data-url="${esc(doc.url)}" data-nombre="${esc(doc.nombre)}" style="padding: 2px 8px; font-size: 12px;">
                    <i class="fas fa-download"></i> Descargar
                </button>
            </li>
        `).join('')
        : '<li class="text-gray-500">No hay documentos adjuntos.</li>';
    
    const observacionesHTML = renderObservaciones(tramite.observaciones);

    return `
        <div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <div class="bg-gray-50 px-4 py-3 border-b">
                <h3 class="text-lg font-semibold text-gray-800">Detalles del Trámite</h3>
            </div>
            <div class="p-4">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                    <div>
                        <p><strong>Expediente:</strong> <span class="font-mono">${esc(tramite.expediente)}</span></p>
                        <p><strong>Tipo:</strong> ${esc(nombreTramite(tramite.tipo))}</p>
                        <p><strong>Fecha:</strong> ${new Date(tramite.fecha_creacion).toLocaleString()}</p>
                    </div>
                    <div>
                        <p><strong>Costo:</strong> S/ ${formatCurrency(tramite.costo_total)}</p>
                        <p><strong>Estado:</strong> <span class="status-badge status-${esc(tramite.estado)}">${esc(tramite.estado.replace(/_/g, ' '))}</span></p>
                    </div>
                </div>
                ${detallesHTML(tramite)}
                ${observacionesHTML ? `<div class="mt-4"><h4 class="font-semibold text-gray-700 mb-2">Observaciones del evaluador</h4>${observacionesHTML}</div>` : ''}
                <div class="mt-4">
                    <h4 class="font-semibold text-gray-700 mb-2">Documentos Adjuntos</h4>
                    <ul class="border rounded-lg divide-y">${documentosHTML}</ul>
                </div>
                <div class="mt-4">
                    <h4 class="font-semibold text-gray-700 mb-2">Seguimiento del expediente</h4>
                    <div data-seguimiento-tramite="${esc(tramite.id)}"><p class="hint">Cargando seguimiento...</p></div>
                </div>
            </div>
        </div>`;
}

async function loadTramitesRecientes() {
    const user = JSON.parse(localStorage.getItem('user'));
    const resultadoDiv = document.getElementById('mt-resultado');
    if (!resultadoDiv) return;  // la pestaña ya no está en pantalla
    
    try {
        // Esta sería una nueva endpoint para obtener trámites del usuario
        const tramites = await apiFetch(`/tramites/usuario/${user.dni}`, {
            method: 'GET'
        });
        
        if (!resultadoDiv.isConnected || resultadoDiv.dataset.manual) return;  // cambió de pestaña o ya consultó un expediente

        if (tramites.length === 0) {
            resultadoDiv.innerHTML = `
                <div class="text-center py-8 text-gray-500">
                    <i class="fas fa-folder-open text-4xl mb-4"></i>
                    <p>No tiene trámites registrados</p>
                </div>`;
            return;
        }
        
        const tramitesHTML = tramites.slice(0, 5).map(tramite => `
            <div class="border rounded-lg p-4 mb-3 hover:bg-gray-50 cursor-pointer" data-exp="${esc(tramite.expediente)}" onclick="document.getElementById('mt-input-expediente').value=this.dataset.exp; document.getElementById('mt-form-consulta').dispatchEvent(new Event('submit'));">
                <div class="flex justify-between items-start">
                    <div>
                        <p class="font-semibold">${esc(nombreTramite(tramite.tipo))}</p>
                        <p class="text-sm text-gray-600">Expediente: ${esc(tramite.expediente)}</p>
                    </div>
                    <span class="status-badge status-${esc(tramite.estado)}">${esc(tramite.estado.replace(/_/g, ' '))}</span>
                </div>
                <p class="text-sm text-gray-500 mt-2">Creado: ${new Date(tramite.fecha_creacion).toLocaleDateString()}</p>
            </div>
        `).join('');
        
        resultadoDiv.innerHTML = `
            <div class="mb-6">
                <h3 class="text-lg font-semibold text-gray-700 mb-3">Trámites Recientes</h3>
                ${tramitesHTML}
            </div>`;
    } catch (error) {
        if (!resultadoDiv.isConnected || resultadoDiv.dataset.manual) return;
        resultadoDiv.innerHTML = `
            <div class="text-center py-8 text-gray-500">
                <p>Ingrese un número de expediente para consultar</p>
            </div>`;
    }
}

// ===========================================
// LÓGICA: MIS DEUDAS (MEJORADA)
// ===========================================

function initMisDeudasListeners() {
    loadDeudas();
    
    document.getElementById('md-btn-pagar').addEventListener('click', handlePagoDeuda);
}

async function loadDeudas() {
    const user = JSON.parse(localStorage.getItem('user'));
    const divResultado = document.getElementById('md-resultado-deudas');
    if (!divResultado) return;  // la pestaña ya no está en pantalla
    
    try {
        const resultado = await apiFetch('/deudas/consultar', {
            method: 'POST',
            body: JSON.stringify({ dni: user.dni })
        });
        if (!divResultado.isConnected) return;  // el usuario ya cambió de pestaña
        
        appState.mdState.deudas = resultado.deudasMunicipales || [];
        
        let htmlDeudas = '<h4 class="text-lg font-semibold text-gray-700 mb-4">Deudas Municipales</h4>';
        
        if (appState.mdState.deudas.length > 0) {
            htmlDeudas += appState.mdState.deudas.map(deuda => `
                <div class="deuda-item ${deuda.esta_vencida ? 'vencida' : ''} ${['PENDIENTE', 'VENCIDO'].includes(deuda.estado) ? 'clickable' : ''}" 
                     data-deuda-id="${deuda.id}">
                    <div class="deuda-header">
                        <div>
                            <span class="deuda-tipo">${esc(deuda.tipo.replace(/_/g, ' '))}</span>
                            <div class="deuda-periodo">Periodo ${esc(deuda.periodo)}</div>
                        </div>
                        <span class="deuda-total">S/ ${formatCurrency(deuda.monto_total)}</span>
                    </div>
                    <div class="deuda-detalle">
                        <span class="deuda-dato"><i class="fas fa-calendar-day"></i> Vence ${esc(deuda.fecha_vencimiento)}</span>
                        <span class="deuda-dato">Base S/ ${formatCurrency(deuda.monto_base)}</span>
                        ${deuda.esta_vencida ? `<span class="deuda-dato deuda-interes">+ S/ ${formatCurrency(deuda.intereses_moratorios)} de intereses</span>` : ''}
                    </div>
                    <div class="deuda-pie">
                        <span class="status-badge status-${esc(deuda.estado)}">${esc(deuda.estado)}</span>
                        ${['PENDIENTE', 'VENCIDO'].includes(deuda.estado) ? '<span class="deuda-pagar"><i class="fas fa-credit-card"></i> Pagar</span>' : ''}
                    </div>
                </div>
            `).join('');
        } else {
            htmlDeudas += '<p class="text-gray-500">No se encontraron deudas municipales.</p>';
        }
        
        htmlDeudas += '<h4 class="mt-8 text-lg font-semibold text-gray-700 mb-4">Deudas Tributarias (SUNAT)</h4>';
        
        if (resultado.deudasTributarias && resultado.deudasTributarias.length > 0) {
            htmlDeudas += resultado.deudasTributarias.map(deuda => `
                <div class="sunat-item">
                    ${esc(deuda.descripcion)} (${esc(deuda.periodo)}) - <strong>S/ ${formatCurrency(deuda.monto)}</strong>
                </div>
            `).join('');
        } else {
            htmlDeudas += '<p class="text-gray-500">No se encontraron deudas tributarias.</p>';
        }
        
        htmlDeudas += `
            <hr class="my-6">
            <div class="total-general bg-blue-50 p-4 rounded-lg">
                <strong class="text-lg">Total General: S/ ${formatCurrency(resultado.totalGeneral || 0)}</strong>
            </div>`;
        
        divResultado.innerHTML = htmlDeudas;
        
        // Agregar listeners a las deudas clickeables
        divResultado.querySelectorAll('.deuda-item.clickable').forEach(item => {
            item.addEventListener('click', () => {
                const deudaId = parseInt(item.dataset.deudaId);
                const deuda = appState.mdState.deudas.find(d => d.id === deudaId);
                if (deuda) {
                    populatePagarDeudaForm(deuda);
                }
            });
        });
    } catch (error) {
        if (!divResultado.isConnected) return;
        divResultado.innerHTML = `
            <div class="text-center py-8 text-red-500">
                <i class="fas fa-exclamation-circle text-4xl mb-4"></i>
                <p>No se pudieron cargar las deudas. Intente nuevamente.</p>
            </div>`;
    }
}

function populatePagarDeudaForm(deuda) {
    appState.mdState.deudaSeleccionada = deuda;
    
    document.getElementById('md-deuda-tipo').textContent = deuda.tipo.replace(/_/g, ' ');
    document.getElementById('md-deuda-periodo').textContent = deuda.periodo || '';
    document.getElementById('md-deuda-monto').textContent = formatCurrency(deuda.monto_total);
    document.getElementById('md-deuda-desglose').innerHTML = parseFloat(deuda.intereses_moratorios) > 0
        ? `Tributo S/ ${formatCurrency(deuda.monto_base)} + intereses moratorios S/ ${formatCurrency(deuda.intereses_moratorios)}` : '';
    document.querySelectorAll('.deuda-item').forEach(el => el.classList.toggle('selected', el.dataset.deudaId == deuda.id));
    
    const formContainer = document.getElementById('md-form-pago-container');
    formContainer.classList.remove('hidden');
    
    // Scroll suave hacia el formulario de pago
    formContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function handlePagoDeuda() {
    const deuda = appState.mdState.deudaSeleccionada;
    if (!deuda) {
        showAlert('Error', 'No hay deuda seleccionada.', 'warning');
        return;
    }
    const desglose = [];
    if (parseFloat(deuda.intereses_moratorios) > 0) {
        desglose.push({ label: 'Tributo', value: `S/ ${formatCurrency(deuda.monto_base)}` });
        desglose.push({ label: 'Intereses moratorios', value: `S/ ${formatCurrency(deuda.intereses_moratorios)}` });
    }
    openPaymentModal({
        titulo: 'Pago de deuda',
        concepto: deuda.tipo.replace(/_/g, ' '),
        referencia: deuda.periodo ? `Periodo ${deuda.periodo}` : '',
        desglose,
        monto: String(deuda.monto_total),
        endpoint: `/pagos/deuda/${deuda.id}`,
        onClose: () => {
            document.getElementById('md-form-pago-container')?.classList.add('hidden');
            appState.mdState.deudaSeleccionada = null;
            loadDeudas();  // siempre se recarga: puede haber cambiado el importe o el estado
        }
    });
}

// ===========================================
// LÓGICA: ASISTENTE IA (CORREGIDA Y MEJORADA)
// ===========================================

function initAsistenteIAListeners() {
    const chatLog = document.getElementById('ai-chat-log');
    const chatForm = document.getElementById('ai-chat-form');
    const chatInput = document.getElementById('ai-chat-input');
    
    function addMessage(sender, text, isError = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${sender}`;
        
        const bubbleDiv = document.createElement('div');
        bubbleDiv.className = `chat-bubble ${isError ? 'error' : ''}`;
        bubbleDiv.style.whiteSpace = 'pre-wrap';
        bubbleDiv.textContent = text;
        
        messageDiv.appendChild(bubbleDiv);
        chatLog.appendChild(messageDiv);
        
        // Scroll automático al último mensaje
        chatLog.scrollTop = chatLog.scrollHeight;
    }

    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const prompt = chatInput.value.trim();
        
        if (!prompt) return;

        // Agregar mensaje del usuario
        addMessage('user', prompt);
        chatInput.value = '';
        chatInput.disabled = true;
        
        // Mensaje de "pensando"
        const thinkingMessage = document.createElement('div');
        thinkingMessage.className = 'chat-message ai thinking';
        thinkingMessage.innerHTML = `
            <div class="chat-bubble">
                <div class="flex items-center">
                    <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600 mr-2"></div>
                    Pensando...
                </div>
            </div>`;
        chatLog.appendChild(thinkingMessage);
        chatLog.scrollTop = chatLog.scrollHeight;

        try {
            const response = await apiFetch('/ai/chat', {
                method: 'POST',
                body: JSON.stringify({ prompt: prompt })
            });
            
            // Reemplazar mensaje de "pensando" con la respuesta real
            const bubble = thinkingMessage.querySelector('.chat-bubble');
            bubble.style.whiteSpace = 'pre-wrap';
            bubble.textContent = response.response;
            thinkingMessage.classList.remove('thinking');
        } catch (error) {
            // Mostrar mensaje de error
            thinkingMessage.querySelector('.chat-bubble').innerHTML = 
                "Lo siento, no pude procesar tu solicitud en este momento. Por favor, intenta nuevamente.";
            thinkingMessage.querySelector('.chat-bubble').classList.add('error');
            thinkingMessage.classList.remove('thinking');
        } finally {
            chatInput.disabled = false;
            chatInput.focus();
        }
    });
    
    // Auto-focus en el input del chat
    chatInput.focus();
}

// ===========================================
// LÓGICA: ADMIN - GENERAL
// ===========================================

let adminStatsTimer = null;

function initAdminGeneralListeners() {
    loadAdminStats();

    // Actualizar estadísticas cada 30 segundos (un solo temporizador)
    clearInterval(adminStatsTimer);
    adminStatsTimer = setInterval(loadAdminStats, 30000);
}

async function loadAdminStats() {
    if (!document.getElementById('admin-tramites-hoy')) {  // ya no está en esa pestaña
        clearInterval(adminStatsTimer);
        return;
    }
    try {
        const stats = await apiFetch('/admin/stats', { method: 'GET' });
        
        document.getElementById('admin-tramites-hoy').textContent = stats.tramitesHoy || '0';
        document.getElementById('admin-tramites-pendientes').textContent = stats.tramitesPendientes || '0';
        document.getElementById('admin-recaudacion-hoy').textContent = formatCurrency(stats.recaudacionHoy || 0);
    } catch (error) {
        console.error('Error cargando estadísticas:', error);
        // Valores por defecto en caso de error
        document.getElementById('admin-tramites-hoy').textContent = '0';
        document.getElementById('admin-tramites-pendientes').textContent = '0';
        document.getElementById('admin-recaudacion-hoy').textContent = '0.00';
    }
}

// ===========================================
// LÓGICA: ADMIN - TRÁMITES
// ===========================================

async function loadAdminTramites() {
    try {
        const tramites = await apiFetch('/tramites/admin/all', { method: 'GET' });
        if (appState.currentTab !== 'revision-tramites') return;  // cambió de pestaña mientras cargaba
        dashboardContent.innerHTML = RENDER.adminRenderTablaTramites(tramites);
        
        // Agregar listeners a los botones de revisar
        document.querySelectorAll('.btn-revisar-tramite').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const tramiteId = e.target.closest('button').dataset.tramiteId;
                revisarTramite(tramiteId);
            });
        });
        
        // Listener para el botón de actualizar
        document.getElementById('btn-refresh-tramites').addEventListener('click', () => {
            loadAdminTramites();
        });
    } catch (error) {
        dashboardContent.innerHTML = RENDER.errorTab(`Error al cargar trámites: ${error.message}`);
    }
}

async function revisarTramite(tramiteId) {
    try {
        const tramite = await apiFetch(`/tramites/${tramiteId}`, { method: 'GET' });
        
        Swal.fire({
            title: `Revisar Trámite ${escapeHtml(tramite.expediente)}`,
            html: `
                <div class="text-left">
                    <p><strong>Ciudadano:</strong> ${esc(tramite.ciudadano_nombre)} (${esc(tramite.ciudadano_dni)})</p>
                    <p><strong>Tipo:</strong> ${esc(nombreTramite(tramite.tipo))}</p>
                    <p><strong>Estado:</strong> ${esc(tramite.estado.replace(/_/g, ' '))}</p>
                    ${(tramite.documentos || []).length ? `<p class="mt-2"><strong>Documentos:</strong></p><ul>${tramite.documentos.map(d => `<li><button type="button" class="btn-doc-download" style="color:#2563eb;text-decoration:underline" data-url="${esc(d.url)}" data-nombre="${esc(d.nombre)}">${esc(d.nombre)}</button></li>`).join('')}</ul>` : ''}
                    ${renderObservaciones(tramite.observaciones) ? `<p class="mt-2"><strong>Historial:</strong></p>${renderObservaciones(tramite.observaciones)}` : ''}
                    <p><strong>Costo:</strong> S/ ${formatCurrency(tramite.costo_total)}</p>
                    <p><strong>Fecha:</strong> ${new Date(tramite.fecha_creacion).toLocaleString()}</p>
                    ${detallesHTML(tramite)}
                    
                    <div class="mt-4">
                        <label for="swal-estado" class="block text-sm font-medium text-gray-700 mb-2">Cambiar Estado:</label>
                        <select id="swal-estado" class="w-full p-2 border border-gray-300 rounded-md">
                            <option value="EN_EVALUACION" ${tramite.estado === 'EN_EVALUACION' ? 'selected' : ''}>En evaluación</option>
                            <option value="OBSERVADO" ${tramite.estado === 'OBSERVADO' ? 'selected' : ''}>Observado</option>
                            <option value="APROBADO" ${tramite.estado === 'APROBADO' ? 'selected' : ''}>Aprobado</option>
                            <option value="RECHAZADO" ${tramite.estado === 'RECHAZADO' ? 'selected' : ''}>Rechazado</option>
                        </select>
                    </div>
                    
                    <div class="mt-3">
                        <label for="swal-observaciones" class="block text-sm font-medium text-gray-700 mb-2">Observaciones:</label>
                        <textarea id="swal-observaciones" class="w-full p-2 border border-gray-300 rounded-md" rows="3" placeholder="Ingrese observaciones..."></textarea>
                    </div>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Actualizar Estado',
            cancelButtonText: 'Cancelar',
            preConfirm: () => {
                const nuevoEstado = document.getElementById('swal-estado').value;
                const observaciones = document.getElementById('swal-observaciones').value;
                
                return apiFetch(`/tramites/${tramiteId}/estado`, {
                    method: 'PUT',
                    body: JSON.stringify({
                        estado: nuevoEstado,
                        observaciones: observaciones
                    })
                });
            }
        }).then((result) => {
            if (result.isConfirmed) {
                showAlert('¡Éxito!', 'Estado del trámite actualizado correctamente.', 'success');
                loadAdminTramites(); // Recargar la tabla
            }
        });
    } catch (error) {
        showAlert('Error', 'No se pudo cargar la información del trámite.', 'error');
    }
}

// ===========================================
// LÓGICA: ADMIN - GESTIÓN DE USUARIOS (MEJORADA)
// ===========================================

function initGestionUsuariosListeners() {
    const userForm = document.getElementById('admin-create-user-form');
    const dniInput = document.getElementById('admin-user-dni');
    const emailInput = document.getElementById('admin-user-email');
    
    // Validación en tiempo real
    dniInput.addEventListener('blur', validateDNIRealTime);
    emailInput.addEventListener('blur', validateEmailRealTime);
    
    userForm.addEventListener('submit', handleCreateUser);
    const rolSel = document.getElementById('admin-user-role');
    rolSel.addEventListener('change', () => document.getElementById('admin-user-area-group').classList.toggle('hidden', rolSel.value !== 'funcionario'));
    
    document.getElementById('btn-export-sql').addEventListener('click', handleExportSQL);
    
    cargarListaUsuarios();
}

function validateDNIRealTime() {
    const dni = document.getElementById('admin-user-dni').value;
    const errorDiv = document.getElementById('admin-dni-error');
    
    if (!validateDNI(dni)) {
        errorDiv.textContent = 'El DNI debe tener exactamente 8 dígitos numéricos.';
        errorDiv.classList.remove('hidden');
        return false;
    } else {
        errorDiv.classList.add('hidden');
        return true;
    }
}

function validateEmailRealTime() {
    const email = document.getElementById('admin-user-email').value;
    const errorDiv = document.getElementById('admin-email-error');
    
    if (email && !validateEmail(email)) {
        errorDiv.textContent = 'Ingrese un email válido.';
        errorDiv.classList.remove('hidden');
        return false;
    } else {
        errorDiv.classList.add('hidden');
        return true;
    }
}

async function handleCreateUser(e) {
    e.preventDefault();
    
    const dni = document.getElementById('admin-user-dni').value;
    const nombre = document.getElementById('admin-user-nombre').value;
    const email = document.getElementById('admin-user-email').value;
    const password = document.getElementById('admin-user-password').value;
    const role = document.getElementById('admin-user-role').value;
    
    // Validaciones
    if (!validateDNIRealTime()) return;
    if (!validateEmailRealTime()) return;
    
    if (!dni || !nombre || !password) {
        showAlert('Error', 'DNI, Nombre y Contraseña son obligatorios.', 'warning');
        return;
    }
    
    if (password.length < 6) {
        showAlert('Error', 'La contraseña debe tener al menos 6 caracteres.', 'warning');
        return;
    }
    
    try {
        const nuevoUsuario = await apiFetch('/admin/ciudadanos', {
            method: 'POST',
            body: JSON.stringify({
                dni: dni,
                nombre: nombre,
                email: email || null,
                password: password,
                role: role,
                area: role === 'funcionario' ? document.getElementById('admin-user-area').value : null
            })
        });
        
        showAlert('¡Éxito!', `Usuario ${nuevoUsuario.nombre} creado correctamente.`, 'success');
        document.getElementById('admin-create-user-form').reset();
        document.getElementById('admin-user-area-group').classList.add('hidden');
        cargarListaUsuarios();
    } catch (error) {
        console.error('Error al crear usuario:', error);
    }
}

async function cargarListaUsuarios() {
    const userListBody = document.getElementById('admin-user-list-body');
    
    try {
        const usuarios = await apiFetch('/admin/ciudadanos', { method: 'GET' });
        if (!userListBody.isConnected) return;  // cambió de pestaña mientras cargaba
        
        if (usuarios.length === 0) {
            userListBody.innerHTML = '<tr><td colspan="5" class="text-center py-8 text-gray-500">No hay usuarios registrados.</td></tr>';
            return;
        }
        
        userListBody.innerHTML = usuarios.map(user => `
            <tr>
                <td class="font-mono">${esc(user.dni)}</td>
                <td>${esc(user.nombre)}</td>
                <td>${user.email ? esc(user.email) : '<span class="text-gray-500">N/A</span>'}</td>
                <td>
                    <span class="status-badge status-${user.role === 'admin' ? 'admin' : 'ciudadano'}">
                        ${esc(user.role)}
                    </span>${user.area ? `<div class="text-xs text-gray-500 mt-1">${esc(AREAS_UI[user.area] || user.area)}</div>` : ''}
                </td>
                <td>
                    <button class="btn btn-secundario btn-sm" onclick="resetUserPassword(this.dataset.dni)" data-dni="${esc(user.dni)}" title="Resetear Contraseña">
                        <i class="fas fa-key"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (error) {
        userListBody.innerHTML = '<tr><td colspan="5" class="text-center py-8 text-red-500">Error al cargar usuarios.</td></tr>';
    }
}

async function resetUserPassword(dni) {
    const result = await showConfirmAlert(
        'Resetear Contraseña',
        `¿Está seguro que desea resetear la contraseña del usuario con DNI ${escapeHtml(dni)}?`,
        'warning'
    );
    
    if (result.isConfirmed) {
        try {
            const nuevaPassword = await apiFetch(`/admin/usuarios/${dni}/reset-password`, {
                method: 'POST'
            });
            
            Swal.fire({
                title: 'Contraseña Reseteada',
                html: `La nueva contraseña temporal es: <strong>${esc(nuevaPassword.password)}</strong><br><br>Comparta esta contraseña con el usuario.`,
                icon: 'success',
                confirmButtonText: 'Copiar Contraseña',
                showCancelButton: true,
                cancelButtonText: 'Cerrar'
            }).then((result) => {
                if (result.isConfirmed) {
                    navigator.clipboard.writeText(nuevaPassword.password);
                    showAlert('¡Copiado!', 'Contraseña copiada al portapapeles.', 'success');
                }
            });
        } catch (error) {
            showAlert('Error', 'No se pudo resetear la contraseña.', 'error');
        }
    }
}

async function handleExportSQL() {
    try {
        await apiFetchFile('/admin/export/ciudadanos.sql', `backup_ciudadanos_${new Date().toISOString().split('T')[0]}.sql`);
    } catch (error) {
        // El error ya fue manejado en apiFetchFile
    }
}

// ===========================================
// LÓGICA: ADMIN - MÉTRICAS IA
// ===========================================

function initMetricasIAListeners() {
    loadMetricasIA();
    
    // Actualizar métricas cada 60 segundos
    setInterval(loadMetricasIA, 60000);
}

async function loadMetricasIA() {
    try {
        const metricas = await apiFetch('/ai/metricas', { method: 'GET' });
        
        document.getElementById('metricas-consultas-dia').textContent = metricas.consultasDia || '0';
        document.getElementById('metricas-satisfaccion').textContent = metricas.satisfaccion == null ? 'N/D' : `${metricas.satisfaccion}%`;
    } catch (error) {
        console.error('Error cargando métricas IA:', error);
        // Valores por defecto
        document.getElementById('metricas-consultas-dia').textContent = '0';
        document.getElementById('metricas-satisfaccion').textContent = 'N/D';
    }
}

// ===========================================
// INICIALIZACIÓN MEJORADA
// ===========================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Aplicación Municipal iniciada');
    
    // Verificar dependencias
    if (typeof Swal === 'undefined') {
        console.error('SweetAlert2 no está cargado');
        alert('Error: SweetAlert2 no está cargado. La aplicación puede no funcionar correctamente.');
    }
    
    // Configurar listeners del login
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
        
        // Auto-focus en el DNI al cargar la página
        setTimeout(() => {
            if (loginDni && !localStorage.getItem('token')) {
                loginDni.focus();
            }
        }, 100);
    }
    
    if (logoutButton) {
        logoutButton.addEventListener('click', handleLogout);
    }

    // Comprobar sesión existente
    const savedUser = localStorage.getItem('user');
    const token = localStorage.getItem('token');
    
    if (savedUser && token) {
        try {
            const user = JSON.parse(savedUser);
            console.log('Sesión activa encontrada:', user.name);
            appState.currentUser = user;
            showDashboard(user);
        } catch (e) {
            console.error('Error al parsear usuario guardado:', e);
            handleLogout();
        }
    } else {
        // Asegurarse de que solo se vea el login
        loginPage.classList.remove('hidden');
        dashboardContainer.classList.add('hidden');
    }
    
    // Manejar errores no capturados
    window.addEventListener('error', (e) => {
        console.error('Error no capturado:', e.error);
    });
    
    window.addEventListener('unhandledrejection', (e) => {
        console.error('Promesa rechazada no manejada:', e.reason);
    });
});

// ===========================================
// FUNCIONES GLOBALES PARA DESARROLLO
// ===========================================

// Solo disponible en desarrollo
if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    window.debugApp = {
        getState: () => ({ ...appState }),
        clearStorage: () => {
            localStorage.clear();
            location.reload();
        },
        simulateError: () => {
            throw new Error('Error de prueba desde la consola');
        }
    };
    
    console.log('🔧 Herramientas de desarrollo disponibles: window.debugApp');
}