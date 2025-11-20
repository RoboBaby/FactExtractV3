// Clusters browser JavaScript

let currentClustersPage = 1;
let currentClustersPageSize = 50;

async function loadClusters(page = 1) {
    currentClustersPage = page;
    
    try {
        const params = new URLSearchParams({
            page: page,
            page_size: currentClustersPageSize
        });
        
        const minSize = document.getElementById('cluster-filter-size')?.value;
        if (minSize) params.append('min_size', minSize);
        
        const data = await apiCall(`/clusters?${params.toString()}`);
        
        updateClustersTable(data.clusters);
        updateClustersPagination(data.page, data.total_pages, data.total);
    } catch (error) {
        console.error('Error loading clusters:', error);
        document.getElementById('clusters-table-body').innerHTML = 
            `<tr><td colspan="6" class="text-center text-danger">Error: ${error.message}</td></tr>`;
    }
}

function updateClustersTable(clusters) {
    const tbody = document.getElementById('clusters-table-body');
    
    if (clusters.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No clusters found</td></tr>';
        return;
    }
    
    tbody.innerHTML = clusters.map(cluster => `
        <tr onclick="showClusterDetail(${cluster.cluster_id})">
            <td><strong>${cluster.cluster_id}</strong></td>
            <td><code>${truncate(cluster.representative_fact_id, 20)}</code></td>
            <td><span class="badge bg-warning">${cluster.member_count}</span></td>
            <td>${formatDate(cluster.first_seen)}</td>
            <td>${cluster.avg_support ? cluster.avg_support.toFixed(2) : '-'}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="event.stopPropagation(); showClusterDetail(${cluster.cluster_id})">
                    <i class="bi bi-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function updateClustersPagination(currentPage, totalPages, total) {
    const pagination = document.getElementById('clusters-pagination');
    
    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }
    
    let html = '';
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="loadClusters(${currentPage - 1}); return false;">Previous</a>
    </li>`;
    
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="loadClusters(1); return false;">1</a></li>`;
        if (startPage > 2) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
    }
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" onclick="loadClusters(${i}); return false;">${i}</a>
        </li>`;
    }
    
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        html += `<li class="page-item"><a class="page-link" href="#" onclick="loadClusters(${totalPages}); return false;">${totalPages}</a></li>`;
    }
    
    html += `<li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="loadClusters(${currentPage + 1}); return false;">Next</a>
    </li>`;
    
    pagination.innerHTML = html;
}

async function showClusterDetail(clusterId) {
    const modal = new bootstrap.Modal(document.getElementById('clusterDetailModal'));
    const content = document.getElementById('cluster-detail-content');
    content.innerHTML = '<div class="text-center"><div class="spinner-border" role="status"></div></div>';
    modal.show();
    
    try {
        const cluster = await apiCall(`/clusters/${clusterId}`);
        
        let html = `
            <div class="fact-detail-section">
                <h6>Cluster Information</h6>
                <p><strong>Cluster ID:</strong> ${cluster.cluster_id}</p>
                <p><strong>Representative Fact:</strong> <code>${cluster.representative_fact_id}</code></p>
                <p><strong>Member Count:</strong> ${cluster.member_facts.length}</p>
            </div>
            
            <div class="fact-detail-section">
                <h6>Member Facts (Duplicates)</h6>
                <div class="list-group">
                    ${cluster.member_facts.map(fact => `
                        <div class="cluster-member">
                            <div class="d-flex w-100 justify-content-between">
                                <div class="flex-grow-1">
                                    <h6 class="mb-1">${escapeHtml(fact.subject)} <strong>${escapeHtml(fact.predicate)}</strong> ${escapeHtml(fact.object || '(no object)')}</h6>
                                    <p class="mb-1 small">${escapeHtml(truncate(fact.canonical_string, 100))}</p>
                                    <small class="text-muted">Video: <code>${truncate(fact.video_id, 15)}</code> | Channel: <code>${fact.channel_id}</code></small>
                                </div>
                                <div>
                                    <button class="btn btn-sm btn-outline-primary" onclick="showFactDetail('${fact.fact_id}')">
                                        <i class="bi bi-eye"></i> View
                                    </button>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
        
        content.innerHTML = html;
    } catch (error) {
        content.innerHTML = `<div class="alert alert-danger">Error loading cluster: ${error.message}</div>`;
    }
}

