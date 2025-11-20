// Entities browser JavaScript

let currentEntitiesPage = 1;
let currentEntitiesPageSize = 50;

async function loadEntities(page = 1) {
    currentEntitiesPage = page;
    
    try {
        const params = new URLSearchParams({
            page: page,
            page_size: currentEntitiesPageSize
        });
        
        const search = document.getElementById('entity-filter-search')?.value;
        const hasQid = document.getElementById('entity-filter-qid')?.value;
        const minConf = document.getElementById('entity-filter-conf')?.value;
        
        if (search) params.append('search', search);
        if (hasQid) params.append('has_qid', hasQid);
        if (minConf) params.append('min_link_conf', minConf);
        
        const data = await apiCall(`/entities?${params.toString()}`);
        
        updateEntitiesTable(data.entities);
        updateEntitiesPagination(data.page, data.total_pages, data.total);
    } catch (error) {
        console.error('Error loading entities:', error);
        document.getElementById('entities-table-body').innerHTML = 
            `<tr><td colspan="6" class="text-center text-danger">Error: ${error.message}</td></tr>`;
    }
}

function updateEntitiesTable(entities) {
    const tbody = document.getElementById('entities-table-body');
    
    if (entities.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No entities found</td></tr>';
        return;
    }
    
    tbody.innerHTML = entities.map(entity => `
        <tr onclick="showEntityDetail('${entity.entity_key}')">
            <td><strong>${escapeHtml(entity.surface)}</strong></td>
            <td>${entity.qid ? `<a href="https://www.wikidata.org/wiki/${entity.qid}" target="_blank" class="wikidata-link">${entity.qid}</a>` : '<span class="text-muted">-</span>'}</td>
            <td><code>${truncate(entity.local_id || '-', 20)}</code></td>
            <td>${entity.link_conf ? `<span class="badge bg-info">${(entity.link_conf * 100).toFixed(0)}%</span>` : '<span class="text-muted">-</span>'}</td>
            <td><span class="badge bg-secondary">${entity.fact_count}</span></td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="event.stopPropagation(); showEntityDetail('${entity.entity_key}')">
                    <i class="bi bi-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function updateEntitiesPagination(currentPage, totalPages, total) {
    const pagination = document.getElementById('entities-pagination');
    
    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }
    
    let html = '';
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="loadEntities(${currentPage - 1}); return false;">Previous</a>
    </li>`;
    
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="loadEntities(1); return false;">1</a></li>`;
        if (startPage > 2) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
    }
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" onclick="loadEntities(${i}); return false;">${i}</a>
        </li>`;
    }
    
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        html += `<li class="page-item"><a class="page-link" href="#" onclick="loadEntities(${totalPages}); return false;">${totalPages}</a></li>`;
    }
    
    html += `<li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="loadEntities(${currentPage + 1}); return false;">Next</a>
    </li>`;
    
    pagination.innerHTML = html;
}

async function showEntityDetail(entityKey) {
    const modal = new bootstrap.Modal(document.getElementById('entityDetailModal'));
    const content = document.getElementById('entity-detail-content');
    content.innerHTML = '<div class="text-center"><div class="spinner-border" role="status"></div></div>';
    modal.show();
    
    try {
        const entity = await apiCall(`/entities/${encodeURIComponent(entityKey)}`);
        
        let html = `
            <div class="fact-detail-section">
                <h6>Entity Information</h6>
                <p><strong>Surface:</strong> ${escapeHtml(entity.surface)}</p>
                ${entity.qid ? `<p><strong>Wikidata QID:</strong> <a href="https://www.wikidata.org/wiki/${entity.qid}" target="_blank" class="wikidata-link">${entity.qid}</a></p>` : ''}
                ${entity.local_id ? `<p><strong>Local ID:</strong> <code>${entity.local_id}</code></p>` : ''}
                ${entity.link_conf ? `<p><strong>Link Confidence:</strong> ${(entity.link_conf * 100).toFixed(1)}%</p>` : ''}
            </div>
        `;
        
        if (entity.facts_as_subject && entity.facts_as_subject.length > 0) {
            html += `
                <div class="fact-detail-section">
                    <h6>Facts as Subject (${entity.facts_as_subject.length})</h6>
                    <div class="list-group">
                        ${entity.facts_as_subject.map(fact => `
                            <a href="#" class="list-group-item list-group-item-action" onclick="showFactDetail('${fact.fact_id}'); return false;">
                                <div class="d-flex w-100 justify-content-between">
                                    <div>
                                        <h6 class="mb-1">${escapeHtml(fact.predicate_frame)}</h6>
                                        <p class="mb-1">${escapeHtml(truncate(fact.canonical_string, 80))}</p>
                                        ${fact.object_surface ? `<small>Object: ${escapeHtml(fact.object_surface)}</small>` : ''}
                                    </div>
                                </div>
                            </a>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        
        if (entity.facts_as_object && entity.facts_as_object.length > 0) {
            html += `
                <div class="fact-detail-section">
                    <h6>Facts as Object (${entity.facts_as_object.length})</h6>
                    <div class="list-group">
                        ${entity.facts_as_object.map(fact => `
                            <a href="#" class="list-group-item list-group-item-action" onclick="showFactDetail('${fact.fact_id}'); return false;">
                                <div class="d-flex w-100 justify-content-between">
                                    <div>
                                        <h6 class="mb-1">${escapeHtml(fact.predicate_frame)}</h6>
                                        <p class="mb-1">${escapeHtml(truncate(fact.canonical_string, 80))}</p>
                                        ${fact.subject_surface ? `<small>Subject: ${escapeHtml(fact.subject_surface)}</small>` : ''}
                                    </div>
                                </div>
                            </a>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        
        content.innerHTML = html;
    } catch (error) {
        content.innerHTML = `<div class="alert alert-danger">Error loading entity: ${error.message}</div>`;
    }
}

