// Main application JavaScript

const API_BASE = '/api';

// Page navigation
document.addEventListener('DOMContentLoaded', function() {
    // Set up navigation
    document.querySelectorAll('[data-page]').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const page = this.getAttribute('data-page');
            showPage(page);
        });
    });
    
    // Show dashboard by default
    showPage('dashboard');
});

function showPage(pageName) {
    // Hide all pages
    document.querySelectorAll('.page-content').forEach(page => {
        page.style.display = 'none';
    });
    
    // Show selected page
    const page = document.getElementById(`page-${pageName}`);
    if (page) {
        page.style.display = 'block';
    }
    
    // Update nav active state
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active');
    });
    document.querySelector(`[data-page="${pageName}"]`).classList.add('active');
    
    // Load page data
    switch(pageName) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'facts':
            loadFacts();
            break;
        case 'entities':
            loadEntities();
            break;
        case 'videos':
            loadVideos();
            break;
        case 'clusters':
            loadClusters();
            break;
        case 'analytics':
            loadAnalytics();
            break;
        case 'search':
            // Search page doesn't auto-load
            break;
    }
}

// Utility function for API calls
async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API call failed:', error);
        throw error;
    }
}

// Format number with commas
function formatNumber(num) {
    return num ? num.toLocaleString() : '-';
}

// Format percentage
function formatPercent(num) {
    return num ? `${num.toFixed(1)}%` : '-';
}

// Format date
function formatDate(dateStr) {
    if (!dateStr) return '-';
    try {
        const date = new Date(dateStr);
        return date.toLocaleString();
    } catch {
        return dateStr;
    }
}

// Truncate text
function truncate(text, maxLength = 50) {
    if (!text) return '';
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
}

