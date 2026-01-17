// Configuration
const API_BASE = "http://localhost:8000";
let currentPatient = "p-1";
let statsInterval = null;
let anomaliesInterval = null;

// Chart Setup
const ctx = document.getElementById('vitalsChart').getContext('2d');
const chart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            { label: 'HR', data: [], borderColor: '#ef4444', tension: 0.4, borderWidth: 2, pointRadius: 0 },
            { label: 'SpO2', data: [], borderColor: '#06b6d4', tension: 0.4, borderWidth: 2, pointRadius: 0 }
        ]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false, // Disable animation for performance on high-freq updates
        interaction: { intersect: false },
        plugins: { legend: { labels: { color: '#94a3b8' } } },
        scales: {
            x: { display: false }, // Time axis hidden for cleanliness
            y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } }
        }
    }
});

function changePatient() {
    const val = document.getElementById('patientIdInput').value;
    if (val) {
        currentPatient = val;
        // Reset chart
        chart.data.labels = [];
        chart.data.datasets.forEach(ds => ds.data = []);
        chart.update();
        fetchPatientData(); // Immediate update
    }
}

async function fetchPatientData() {
    try {
        // 1. Current Vitals
        const res = await fetch(`${API_BASE}/patient/${currentPatient}`);
        if (res.ok) {
            const data = await res.json();
            const v = data.latest_vitals;

            document.getElementById('val-hr').textContent = v.hr;
            document.getElementById('val-spo2').textContent = v.spo2;
            document.getElementById('val-bp').textContent = v.bp;
            document.getElementById('val-temp').textContent = v.temp;

            // Update Chart (Shift Buffer)
            const timeStr = new Date(v.timestamp).toLocaleTimeString();
            if (chart.data.labels.length > 50) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
                chart.data.datasets[1].data.shift();
            }
            // Avoid duplicate pushing if timestamp hasn't changed? 
            // Ideally we check last timestamp.
            const lastTs = chart.data.labels[chart.data.labels.length - 1];
            if (lastTs !== timeStr) {
                chart.data.labels.push(timeStr);
                chart.data.datasets[0].data.push(v.hr);
                chart.data.datasets[1].data.push(v.spo2);
                chart.update();
            }
        }

        // 2. Timeline
        const resTime = await fetch(`${API_BASE}/patient/${currentPatient}/timeline`);
        if (resTime.ok) {
            const events = await resTime.json();
            const tbody = document.querySelector('#timelineTable tbody');
            tbody.innerHTML = events.slice(0, 10).map(e => `
                <tr>
                    <td>${new Date(e.timestamp).toLocaleTimeString()}</td>
                    <td>${e.hr}</td>
                    <td>${e.spo2}</td>
                </tr>
            `).join('');
        }

    } catch (e) {
        console.error("Fetch error", e);
    }
}

async function fetchAnomalies() {
    try {
        const res = await fetch(`${API_BASE}/anomalies`);
        if (res.ok) {
            const anomalies = await res.json();
            const container = document.getElementById('anomalyFeed');

            // Re-render feed (simple approach)
            container.innerHTML = anomalies.map(a => `
                <div class="feed-item">
                    <div class="meta">
                        <span>${new Date(a.timestamp).toLocaleTimeString()}</span>
                        <span>p-ID: ${a.patient_id}</span>
                    </div>
                    <div class="title">
                        <span class="tag tag-${a.type === 'spike' ? 'spike' : 'drift'}">${a.type}</span>
                        Score: ${a.score.toFixed(2)}
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error("Anomaly fetch error", e);
    }
}

// Start Polling
statsInterval = setInterval(fetchPatientData, 1000); // 1s
anomaliesInterval = setInterval(fetchAnomalies, 2000); // 2s

// Initial load
fetchPatientData();
fetchAnomalies();
