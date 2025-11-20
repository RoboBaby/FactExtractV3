// Dashboard JavaScript

let timelineChart = null;
let predicatesChart = null;
let entitiesSubjectsChart = null;
let channelsChart = null;

async function loadDashboard() {
    try {
        // Load stats
        const stats = await apiCall('/stats');
        updateMetricsCards(stats);
        
        // Load timeline data
        const timeline = await apiCall('/analytics/timeline?days=30');
        updateTimelineChart(timeline);
        
        // Load predicate distribution
        const predicates = await apiCall('/analytics/predicates');
        updatePredicatesChart(predicates);
        
        // Load entity distribution
        const entities = await apiCall('/analytics/entities');
        updateEntitiesChart(entities);
        
        // Load channel distribution
        const channels = await apiCall('/analytics/channels');
        updateChannelsChart(channels);
    } catch (error) {
        console.error('Error loading dashboard:', error);
        alert('Failed to load dashboard data: ' + error.message);
    }
}

function updateMetricsCards(stats) {
    document.getElementById('metric-total-facts').textContent = formatNumber(stats.total_facts);
    document.getElementById('metric-total-entities').textContent = formatNumber(stats.total_entities);
    document.getElementById('metric-total-videos').textContent = formatNumber(stats.total_videos);
    document.getElementById('metric-total-clusters').textContent = formatNumber(stats.total_clusters);
    document.getElementById('metric-facts-per-video-avg').textContent = formatNumber(stats.facts_per_video_avg);
    document.getElementById('metric-entity-linking-rate').textContent = formatPercent(stats.entity_linking_success_rate);
    document.getElementById('metric-duplicate-rate').textContent = formatPercent(stats.duplicate_rate);
    document.getElementById('metric-avg-verify').textContent = stats.avg_verify_support ? stats.avg_verify_support.toFixed(2) : 'N/A';
}

function updateTimelineChart(data) {
    const ctx = document.getElementById('chart-timeline');
    if (!ctx) return;
    
    if (timelineChart) {
        timelineChart.destroy();
    }
    
    timelineChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.dates,
            datasets: [{
                label: 'Facts',
                data: data.facts_count,
                borderColor: 'rgb(75, 192, 192)',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}

function updatePredicatesChart(data) {
    const ctx = document.getElementById('chart-predicates');
    if (!ctx) return;
    
    if (predicatesChart) {
        predicatesChart.destroy();
    }
    
    const top20 = data.predicates.slice(0, 20);
    
    predicatesChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: top20.map(p => p.predicate),
            datasets: [{
                label: 'Frequency',
                data: top20.map(p => p.count),
                backgroundColor: 'rgba(54, 162, 235, 0.6)',
                borderColor: 'rgba(54, 162, 235, 1)',
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

function updateEntitiesChart(data) {
    const ctx = document.getElementById('chart-entities-subjects');
    if (!ctx) return;
    
    if (entitiesSubjectsChart) {
        entitiesSubjectsChart.destroy();
    }
    
    const top20 = data.top_subjects.slice(0, 20);
    
    entitiesSubjectsChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: top20.map(e => truncate(e.entity, 20)),
            datasets: [{
                label: 'As Subject',
                data: top20.map(e => e.count),
                backgroundColor: 'rgba(255, 99, 132, 0.6)',
                borderColor: 'rgba(255, 99, 132, 1)',
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

function updateChannelsChart(data) {
    const ctx = document.getElementById('chart-channels');
    if (!ctx) return;
    
    if (channelsChart) {
        channelsChart.destroy();
    }
    
    channelsChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: data.channels.map(c => c.channel_id),
            datasets: [{
                label: 'Facts',
                data: data.channels.map(c => c.fact_count),
                backgroundColor: [
                    'rgba(255, 99, 132, 0.6)',
                    'rgba(54, 162, 235, 0.6)',
                    'rgba(255, 206, 86, 0.6)',
                    'rgba(75, 192, 192, 0.6)',
                    'rgba(153, 102, 255, 0.6)',
                    'rgba(255, 159, 64, 0.6)'
                ]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right'
                }
            }
        }
    });
}

