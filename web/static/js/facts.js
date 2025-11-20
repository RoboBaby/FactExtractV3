// Facts browser JavaScript

let currentFactsPage = 1;
let currentFactsPageSize = 50;

async function loadFacts(page = 1) {
    currentFactsPage = page;
    
    try {
        const params = new URLSearchParams({
            page: page,
            page_size: currentFactsPageSize
        });
        
        // Add filters
        const search = document.getElementById('filter-search')?.value;
        const channel = document.getElementById('filter-channel')?.value;
        const predicate = document.getElementById('filter-predicate')?.value;
        const elConf = document.getElementById('filter-el-conf')?.value;
        const verify = document.getElementById('filter-verify')?.value;
        
        if (search) params.append('search', search);
        if (channel) params.append('channel_id', channel);
        if (predicate) params.append('predicate', predicate);
        if (elConf) params.append('min_el_conf', elConf);
        if (verify) params.append('min_verify_support', verify);
        
        const data = await apiCall(`/facts?${params.toString()}`);
        
        updateFactsTable(data.facts);
        updateFactsPagination(data.page, data.total_pages, data.total);
    } catch (error) {
        console.error('Error loading facts:', error);
        document.getElementById('facts-table-body').innerHTML = 
            `<tr><td colspan="8" class="text-center text-danger">Error: ${error.message}</td></tr>`;
    }
}

function updateFactsTable(facts) {
    const tbody = document.getElementById('facts-table-body');
    
    if (facts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">No facts found</td></tr>';
        return;
    }
    
    tbody.innerHTML = facts.map(fact => `
        <tr onclick="showFactDetail('${fact.fact_id}')">
            <td><code>${truncate(fact.fact_id, 12)}</code></td>
            <td>${escapeHtml(fact.subject)}</td>
            <td><strong>${escapeHtml(fact.predicate)}</strong></td>
            <td>${escapeHtml(fact.object || '(no object)')}</td>
            <td><code>${truncate(fact.video_id, 12)}</code></td>
            <td><span class="badge bg-info">${(fact.el_conf * 100).toFixed(0)}%</span></td>
            <td>${fact.verify_support ? `<span class="badge bg-success">${(fact.verify_support * 100).toFixed(0)}%</span>` : '<span class="text-muted">N/A</span>'}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="event.stopPropagation(); showFactDetail('${fact.fact_id}')">
                    <i class="bi bi-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function updateFactsPagination(currentPage, totalPages, total) {
    const pagination = document.getElementById('facts-pagination');
    
    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }
    
    let html = '';
    
    // Previous
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="loadFacts(${currentPage - 1}); return false;">Previous</a>
    </li>`;
    
    // Page numbers
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="loadFacts(1); return false;">1</a></li>`;
        if (startPage > 2) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
    }
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" onclick="loadFacts(${i}); return false;">${i}</a>
        </li>`;
    }
    
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        html += `<li class="page-item"><a class="page-link" href="#" onclick="loadFacts(${totalPages}); return false;">${totalPages}</a></li>`;
    }
    
    // Next
    html += `<li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="loadFacts(${currentPage + 1}); return false;">Next</a>
    </li>`;
    
    pagination.innerHTML = html;
}

async function showFactDetail(factId) {
    const modal = new bootstrap.Modal(document.getElementById('factDetailModal'));
    const content = document.getElementById('fact-detail-content');
    content.innerHTML = '<div class="text-center"><div class="spinner-border" role="status"></div></div>';
    modal.show();
    
    try {
        const fact = await apiCall(`/facts/${factId}`);
        
        let html = `
            <div class="fact-detail-section">
                <h6>Canonical String</h6>
                <p class="lead">${escapeHtml(fact.canonical_string)}</p>
            </div>
            
            <div class="fact-detail-section">
                <h6>Subject</h6>
                <p>
                    <strong>${escapeHtml(fact.subject.surface)}</strong>
                    ${fact.subject.qid ? `<a href="https://www.wikidata.org/wiki/${fact.subject.qid}" target="_blank" class="wikidata-link ms-2"><i class="bi bi-box-arrow-up-right"></i> ${fact.subject.qid}</a>` : ''}
                    ${fact.subject.local_id ? `<span class="badge bg-secondary ms-2">${fact.subject.local_id}</span>` : ''}
                </p>
                <small class="text-muted">Link Confidence: ${(fact.subject.link_conf * 100).toFixed(1)}%</small>
            </div>
            
            <div class="fact-detail-section">
                <h6>Predicate</h6>
                <p><strong>${escapeHtml(fact.predicate.frame)}</strong></p>
            </div>
        `;
        
        if (fact.object) {
            html += `
                <div class="fact-detail-section">
                    <h6>Object</h6>
                    <p>
                        <strong>${escapeHtml(fact.object.surface)}</strong>
                        ${fact.object.qid ? `<a href="https://www.wikidata.org/wiki/${fact.object.qid}" target="_blank" class="wikidata-link ms-2"><i class="bi bi-box-arrow-up-right"></i> ${fact.object.qid}</a>` : ''}
                    </p>
                </div>
            `;
        } else if (fact.object_literal) {
            html += `
                <div class="fact-detail-section">
                    <h6>Object (Literal)</h6>
                    <p><strong>${escapeHtml(JSON.stringify(fact.object_literal))}</strong></p>
                </div>
            `;
        }
        
        if (fact.qualifiers && Object.keys(fact.qualifiers).length > 0) {
            html += `
                <div class="fact-detail-section">
                    <h6>Qualifiers</h6>
                    <pre>${escapeHtml(JSON.stringify(fact.qualifiers, null, 2))}</pre>
                </div>
            `;
        }
        
        if (fact.evidence) {
            html += `
                <div class="fact-detail-section">
                    <h6>Evidence</h6>
                    <pre>${escapeHtml(JSON.stringify(fact.evidence, null, 2))}</pre>
                </div>
            `;
        }
        
        html += `
            <div class="fact-detail-section">
                <h6>Confidence Scores</h6>
                <ul>
                    <li>Entity Linking: ${((fact.conf.el || 0) * 100).toFixed(1)}%</li>
                    <li>SRL: ${((fact.conf.srl || 0) * 100).toFixed(1)}%</li>
                    <li>Verification Support: ${fact.conf.verify_support ? ((fact.conf.verify_support * 100).toFixed(1)) + '%' : 'N/A'}</li>
                </ul>
            </div>
            
            <div class="fact-detail-section">
                <h6>Metadata</h6>
                <ul>
                    <li>Video ID: <code>${fact.video_id}</code></li>
                    <li>Channel ID: <code>${fact.channel_id}</code></li>
                    ${fact.t_start ? `<li>Time: ${fact.t_start}s - ${fact.t_end || 'N/A'}s</li>` : ''}
                    ${fact.cluster_id ? `<li>Cluster: <a href="#" onclick="showClusterDetail(${fact.cluster_id}); return false;">${fact.cluster_id}</a></li>` : ''}
                </ul>
            </div>
        `;
        
        if (fact.similar_facts && fact.similar_facts.length > 0) {
            html += `
                <div class="fact-detail-section">
                    <h6>Similar Facts</h6>
                    <div class="list-group">
                        ${fact.similar_facts.map(sf => `
                            <a href="#" class="list-group-item list-group-item-action" onclick="showFactDetail('${sf.fact_id}'); return false;">
                                <div class="d-flex w-100 justify-content-between">
                                    <h6 class="mb-1">${escapeHtml(truncate(sf.canonical_string || sf.fact_id, 60))}</h6>
                                    ${sf.similarity_score ? `<small class="text-muted">${(sf.similarity_score * 100).toFixed(1)}%</small>` : ''}
                                </div>
                            </a>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        
        content.innerHTML = html;
    } catch (error) {
        content.innerHTML = `<div class="alert alert-danger">Error loading fact: ${error.message}</div>`;
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

