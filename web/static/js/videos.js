// Videos browser JavaScript

let currentVideosPage = 1;
let currentVideosPageSize = 50;

async function loadVideos(page = 1) {
    currentVideosPage = page;
    
    try {
        const params = new URLSearchParams({
            page: page,
            page_size: currentVideosPageSize
        });
        
        const channel = document.getElementById('video-filter-channel')?.value;
        if (channel) params.append('channel_id', channel);
        
        const data = await apiCall(`/videos?${params.toString()}`);
        
        updateVideosTable(data.videos);
        updateVideosPagination(data.page, data.total_pages, data.total);
    } catch (error) {
        console.error('Error loading videos:', error);
        document.getElementById('videos-table-body').innerHTML = 
            `<tr><td colspan="5" class="text-center text-danger">Error: ${error.message}</td></tr>`;
    }
}

function updateVideosTable(videos) {
    const tbody = document.getElementById('videos-table-body');
    
    if (videos.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No videos found</td></tr>';
        return;
    }
    
    tbody.innerHTML = videos.map(video => `
        <tr onclick="showVideoDetail('${video.video_id}')">
            <td><code>${truncate(video.video_id, 20)}</code></td>
            <td><code>${escapeHtml(video.channel_id)}</code></td>
            <td>${formatDate(video.publish_time)}</td>
            <td><span class="badge bg-primary">${video.fact_count}</span></td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="event.stopPropagation(); showVideoDetail('${video.video_id}')">
                    <i class="bi bi-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function updateVideosPagination(currentPage, totalPages, total) {
    const pagination = document.getElementById('videos-pagination');
    
    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }
    
    let html = '';
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="loadVideos(${currentPage - 1}); return false;">Previous</a>
    </li>`;
    
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="loadVideos(1); return false;">1</a></li>`;
        if (startPage > 2) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
    }
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" onclick="loadVideos(${i}); return false;">${i}</a>
        </li>`;
    }
    
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        html += `<li class="page-item"><a class="page-link" href="#" onclick="loadVideos(${totalPages}); return false;">${totalPages}</a></li>`;
    }
    
    html += `<li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="loadVideos(${currentPage + 1}); return false;">Next</a>
    </li>`;
    
    pagination.innerHTML = html;
}

async function showVideoDetail(videoId) {
    const modal = new bootstrap.Modal(document.getElementById('videoDetailModal'));
    const content = document.getElementById('video-detail-content');
    content.innerHTML = '<div class="text-center"><div class="spinner-border" role="status"></div></div>';
    modal.show();
    
    try {
        const video = await apiCall(`/videos/${videoId}`);
        
        let html = `
            <div class="fact-detail-section">
                <h6>Video Information</h6>
                <p><strong>Video ID:</strong> <code>${video.video_id}</code></p>
                <p><strong>Channel ID:</strong> <code>${video.channel_id}</code></p>
                ${video.publish_time ? `<p><strong>Publish Time:</strong> ${formatDate(video.publish_time)}</p>` : ''}
            </div>
            
            <div class="fact-detail-section">
                <h6>Quality Metrics</h6>
                <ul>
                    <li>Total Facts: <strong>${video.quality_metrics.fact_count}</strong></li>
                    <li>Avg Entity Linking Confidence: <strong>${video.quality_metrics.avg_el_conf}</strong></li>
                    ${video.quality_metrics.avg_verify_support ? `<li>Avg Verification Support: <strong>${video.quality_metrics.avg_verify_support}</strong></li>` : ''}
                </ul>
            </div>
            
            <div class="fact-detail-section">
                <h6>Facts (${video.facts.length})</h6>
                <div class="table-responsive">
                    <table class="table table-sm table-hover">
                        <thead>
                            <tr>
                                <th>Subject</th>
                                <th>Predicate</th>
                                <th>Object</th>
                                <th>Time</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${video.facts.map(fact => `
                                <tr>
                                    <td>${escapeHtml(fact.subject)}</td>
                                    <td><strong>${escapeHtml(fact.predicate)}</strong></td>
                                    <td>${escapeHtml(fact.object || '(no object)')}</td>
                                    <td>${fact.t_start ? `${fact.t_start}s` : '-'}</td>
                                    <td>
                                        <button class="btn btn-sm btn-outline-primary" onclick="showFactDetail('${fact.fact_id}')">
                                            <i class="bi bi-eye"></i>
                                        </button>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
        
        content.innerHTML = html;
    } catch (error) {
        content.innerHTML = `<div class="alert alert-danger">Error loading video: ${error.message}</div>`;
    }
}

