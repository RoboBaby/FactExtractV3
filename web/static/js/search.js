// Semantic search JavaScript

async function performSemanticSearch() {
    const query = document.getElementById('search-query')?.value;
    const threshold = document.getElementById('search-threshold')?.value || 0.5;
    
    if (!query || query.trim().length === 0) {
        alert('Please enter a search query');
        return;
    }
    
    const resultsDiv = document.getElementById('search-results');
    resultsDiv.innerHTML = '<div class="text-center"><div class="spinner-border" role="status"></div><p>Searching...</p></div>';
    
    try {
        const data = await apiCall(`/search/semantic?query=${encodeURIComponent(query)}&score_threshold=${threshold}`);
        
        if (data.results.length === 0) {
            resultsDiv.innerHTML = '<p class="text-muted text-center">No results found. Try a different query or lower the score threshold.</p>';
            return;
        }
        
        resultsDiv.innerHTML = `
            <h6>Found ${data.total} result(s)</h6>
            <div class="list-group">
                ${data.results.map(result => `
                    <div class="search-result-item">
                        <div class="d-flex w-100 justify-content-between">
                            <div class="flex-grow-1">
                                <h6 class="mb-1">${escapeHtml(result.subject)} <strong>${escapeHtml(result.predicate)}</strong> ${escapeHtml(result.object || '(no object)')}</h6>
                                <p class="mb-1">${escapeHtml(truncate(result.canonical_string, 120))}</p>
                                <small class="text-muted">Video: <code>${truncate(result.video_id, 15)}</code> | Channel: <code>${result.channel_id}</code></small>
                            </div>
                            <div class="ms-3">
                                <span class="similarity-score">${(result.similarity_score * 100).toFixed(1)}%</span>
                                <button class="btn btn-sm btn-outline-primary ms-2" onclick="showFactDetail('${result.fact_id}')">
                                    <i class="bi bi-eye"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        resultsDiv.innerHTML = `<div class="alert alert-danger">Search failed: ${error.message}</div>`;
    }
}

// Allow Enter key to trigger search
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('search-query');
    if (searchInput) {
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                performSemanticSearch();
            }
        });
    }
});

