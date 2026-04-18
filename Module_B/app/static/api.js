const BASE_URL = "http://127.0.0.1:8000";

// Toast notification system
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <div class="notification-content">
            <span class="notification-icon">${type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ'}</span>
            <span class="notification-message">${message}</span>
        </div>
    `;
    
    // Add styles dynamically
    if (!document.querySelector('#notification-styles')) {
        const styles = document.createElement('style');
        styles.id = 'notification-styles';
        styles.textContent = `
            .notification {
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 10000;
                animation: slideIn 0.3s ease-out;
                margin-bottom: 10px;
            }
            
            @keyframes slideIn {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
            
            @keyframes slideOut {
                from {
                    transform: translateX(0);
                    opacity: 1;
                }
                to {
                    transform: translateX(100%);
                    opacity: 0;
                }
            }
            
            .notification-content {
                background: white;
                border-radius: 8px;
                padding: 12px 20px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                display: flex;
                align-items: center;
                gap: 12px;
                min-width: 300px;
                border-left: 4px solid;
            }
            
            .notification-success .notification-content {
                border-left-color: #4caf50;
            }
            
            .notification-error .notification-content {
                border-left-color: #f44336;
            }
            
            .notification-info .notification-content {
                border-left-color: #2196f3;
            }
            
            .notification-icon {
                font-size: 1.2em;
                font-weight: bold;
            }
            
            .notification-success .notification-icon {
                color: #4caf50;
            }
            
            .notification-error .notification-icon {
                color: #f44336;
            }
            
            .notification-info .notification-icon {
                color: #2196f3;
            }
            
            .notification-message {
                color: #333;
                font-size: 14px;
            }
        `;
        document.head.appendChild(styles);
    }
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Loading overlay
function showLoading() {
    let overlay = document.getElementById('loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        overlay.innerHTML = `
            <div class="loading-spinner"></div>
        `;
        const styles = document.createElement('style');
        styles.textContent = `
            #loading-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.7);
                z-index: 9999;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            
            .loading-spinner {
                width: 50px;
                height: 50px;
                border: 5px solid #f3f3f3;
                border-top: 5px solid #667eea;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }
            
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        `;
        document.head.appendChild(styles);
        document.body.appendChild(overlay);
    }
    overlay.style.display = 'flex';
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.style.display = 'none';
    }
}

async function request(url, options = {}) {
    const token = localStorage.getItem("token");

    options.headers = {
        "Content-Type": "application/json",
        ...(options.headers || {})
    };

    if (token) {
        options.headers["Authorization"] = token;
    }

    try {
        showLoading();
        const res = await fetch(url, options);
        
        let data = {};
        try {
            data = await res.json();
        } catch {}

        if (!res.ok) {
            hideLoading();
            showNotification(data.detail || "Request failed", 'error');
            return { error: data.detail || "Request failed" };
        }

        hideLoading();
        return data;

    } catch (err) {
        hideLoading();
        showNotification("Server error. Please check your connection.", 'error');
        return { error: "Server error" };
    }
}

async function login() {
    let email = document.getElementById("email").value;
    let password = document.getElementById("password").value;

    if (!email || !password) {
        showNotification("Please enter both email and password", 'error');
        return;
    }

    let data = await request(`${BASE_URL}/login`, {
        method: "POST",
        body: JSON.stringify({ email, password })
    });

    if (data && data.session_token) {
        localStorage.setItem("token", data.session_token);
        localStorage.setItem("user_name", data.name || "User");
        localStorage.setItem("user_role", data.role || "");
        showNotification("Login Successful! Redirecting...", 'success');
        setTimeout(() => {
            window.location.href = "dashboard.html";
        }, 1000);
    } else {
        showNotification("Invalid credentials", 'error');
    }
}

async function isAuth() {
    const token = localStorage.getItem("token");

    if (!token) {
        window.location.href = "login.html";
        return null;
    }

    const data = await request(`${BASE_URL}/isAuth`);
    
    if (data.error) {
        localStorage.clear();
        window.location.href = "login.html";
        return null;
    }
    
    return data;
}

function logout() {
    localStorage.clear();
    showNotification("Logged out successfully", 'success');
    setTimeout(() => {
        window.location.href = "login.html";
    }, 500);
}

async function getScholarships() {
    return await request(`${BASE_URL}/scholarships`);
}

// FIXED: This function now sends the data as an object matching backend expectations
async function applyScholarship(student_id, scholarship_id) {
    return await request(`${BASE_URL}/apply`, {
        method: "POST",
        body: JSON.stringify({ 
            student_id: student_id, 
            scholarship_id: scholarship_id 
        })
    });
}

async function verifyApplication(application_id, status, remarks) {
    return await request(`${BASE_URL}/verify`, {
        method: "PUT",
        body: JSON.stringify({ application_id, status, remarks })
    });
}

async function releasePayment(application_id, amount, bank_id) {
    return await request(`${BASE_URL}/payment`, {
        method: "POST",
        body: JSON.stringify({ application_id, amount, bank_id })
    });
}

async function createMember(data) {
    return await request(`${BASE_URL}/member`, {
        method: "POST",
        body: JSON.stringify(data)
    });
}

async function deleteScholarship(id) {
    return await request(`${BASE_URL}/scholarship/${id}`, {
        method: "DELETE"
    });
}

async function deleteMember(id) {
    return await request(`${BASE_URL}/member/${id}`, {
        method: "DELETE"
    });
}

async function getProfile() {
    return await request(`${BASE_URL}/profile`);
}
