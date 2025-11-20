// Analytics/Quality JavaScript

let predicateDistChart = null;

async function loadAnalytics() {
    try {
        const quality = await apiCall('/analytics/quality');
        updateQualityMetrics(quality);
        
        const predicates = await apiCall('/analytics/predicates');
        updatePredicateDistChart(predicates);
    } catch (error) {
        console.error('Error loading analytics:', error);
        alert('Failed to load analytics data: ' + error.message);
    }
}

function updateQualityMetrics(quality) {
    // Subject Quality
    const subjQuality = quality.subject_quality;
    document.getElementById('analytics-subject-quality').innerHTML = `
        <ul class="list-unstyled">
            <li><strong>Avg Word Count:</strong> ${subjQuality.avg_word_count}</li>
            <li><strong>Long Subjects (>8 words):</strong> <span class="badge bg-warning">${subjQuality.long_subjects_count}</span></li>
            <li><strong>Fragment Subjects:</strong> <span class="badge bg-danger">${subjQuality.fragment_subjects_count}</span></li>
        </ul>
    `;
    
    // Object Quality
    const objQuality = quality.object_quality;
    document.getElementById('analytics-object-quality').innerHTML = `
        <ul class="list-unstyled">
            <li><strong>Empty Objects:</strong> <span class="badge bg-info">${objQuality.empty_objects_count}</span></li>
        </ul>
    `;
    
    // Entity Linking Quality
    const elQuality = quality.entity_linking_quality;
    document.getElementById('analytics-entity-linking').innerHTML = `
        <ul class="list-unstyled">
            <li><strong>QID Ratio:</strong> ${elQuality.qid_ratio}%</li>
            <li><strong>Avg Link Confidence:</strong> ${elQuality.avg_link_conf}</li>
            <li><strong>Low Confidence Entities:</strong> <span class="badge bg-warning">${elQuality.low_confidence_count}</span></li>
        </ul>
    `;
    
    // Verification Quality
    const verifyQuality = quality.verification_quality;
    document.getElementById('analytics-verification').innerHTML = `
        <ul class="list-unstyled">
            <li><strong>Verified Facts:</strong> ${verifyQuality.verified_count} / ${verifyQuality.total_facts}</li>
            <li><strong>Avg Support:</strong> ${verifyQuality.avg_support || 'N/A'}</li>
            <li><strong>Below Threshold:</strong> <span class="badge bg-danger">${verifyQuality.below_threshold_count}</span></li>
        </ul>
    `;
    
    // Deduplication Quality
    const dedupQuality = quality.deduplication_quality;
    document.getElementById('analytics-deduplication').innerHTML = `
        <ul class="list-unstyled">
            <li><strong>Total Clusters:</strong> ${dedupQuality.cluster_count}</li>
            <li><strong>Avg Cluster Size:</strong> ${dedupQuality.avg_cluster_size}</li>
        </ul>
    `;
}

function updatePredicateDistChart(data) {
    const ctx = document.getElementById('chart-predicate-dist');
    if (!ctx) return;
    
    if (predicateDistChart) {
        predicateDistChart.destroy();
    }
    
    const top20 = data.predicates.slice(0, 20);
    
    predicateDistChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: top20.map(p => p.predicate),
            datasets: [{
                label: 'Frequency',
                data: top20.map(p => p.count),
                backgroundColor: 'rgba(153, 102, 255, 0.6)',
                borderColor: 'rgba(153, 102, 255, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                },
                x: {
                    ticks: {
                        maxRotation: 45,
                        minRotation: 45
                    }
                }
            }
        }
    });
}

