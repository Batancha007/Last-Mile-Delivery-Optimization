#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Delivery Route Optimization Web Interface
Web application for optimizing multiple deliveries into single routes
"""

import json
import pickle
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import os
try:
    from multi_delivery_optimizer import MultiDeliveryOptimizer
    # Global optimizer instance to persist data between requests
    global_optimizer = MultiDeliveryOptimizer()
    MODEL_STATUS = {"loaded": True, "error": None}
except Exception as e:
    print(f"[ERROR] Failed to load models: {e} - multi_delivery_app.py:19")
    global_optimizer = None
    MODEL_STATUS = {"loaded": False, "error": str(e)}

# Fallback in-memory store when optimizer is unavailable
FALLBACK_DELIVERIES = []

class MultiDeliveryHandler(BaseHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        # Use the global optimizer instance
        self.optimizer = global_optimizer
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/' or self.path == '/index.html':
            self.serve_main_page()
        elif self.path == '/optimize':
            self.serve_optimization_page()
        elif self.path == '/results':
            self.serve_results_page()
        elif self.path == '/status':
            self.serve_status()
        elif self.path == '/map':
            self.serve_map_page()
        elif self.path.startswith('/map?'):
            self.serve_map_page()
        else:
            self.send_error(404)
    
    def do_POST(self):
        """Handle POST requests"""
        if self.path == '/add_delivery':
            self.handle_add_delivery()
        elif self.path == '/optimize_routes':
            self.handle_optimize_routes()
        elif self.path == '/clear_deliveries':
            self.handle_clear_deliveries()
        elif self.path == '/remove_delivery':
            self.handle_remove_delivery()
        else:
            self.send_error(404)
    
    def serve_main_page(self):
        """Serve the main page for adding deliveries"""
        html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Last Mile Multi-Company Delivery Optimizer</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }
        
        .main-container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            text-align: center;
            margin-bottom: 40px;
            color: white;
        }
        
        .header h1 {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 10px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }
        
        .header .subtitle {
            font-size: 1.2rem;
            opacity: 0.9;
            font-weight: 300;
        }

        .nav-menu {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-top: 20px;
        }

        .nav-button {
            background: rgba(255,255,255,0.2);
            color: white;
            padding: 12px 25px;
            border-radius: 25px;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s ease;
            border: 2px solid rgba(255,255,255,0.3);
        }

        .nav-button:hover {
            background: rgba(255,255,255,0.3);
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        }

        .nav-button.active {
            background: rgba(255,255,255,0.9);
            color: #667eea;
            border-color: rgba(255,255,255,0.9);
        }
        
        .dashboard {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 30px;
            margin-bottom: 30px;
        }
        
        @media (max-width: 1200px) {
            .dashboard {
                grid-template-columns: 1fr 1fr;
            }
        }
        
        @media (max-width: 768px) {
            .dashboard {
                grid-template-columns: 1fr;
            }
        }
        
        .card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            transition: all 0.3s ease;
        }
        
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 25px 50px rgba(0,0,0,0.15);
        }
        
        .card-header {
            display: flex;
            align-items: center;
            margin-bottom: 25px;
        }
        
        .card-icon {
            width: 50px;
            height: 50px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 15px;
            color: white;
            font-size: 1.5rem;
        }
        
        .card-title {
            font-size: 1.5rem;
            font-weight: 600;
            color: #2c3e50;
        }
        
        .form-grid {
            display: flex;
            flex-direction: column;
            gap: 25px;
        }

        .form-section {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            border-left: 4px solid #3498db;
        }

        .form-section h4 {
            margin: 0 0 15px 0;
            color: #2c3e50;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 15px;
        }

        .form-row:last-child {
            margin-bottom: 0;
        }

        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .checkbox-group input[type="checkbox"] {
            width: auto;
            margin: 0;
        }

        .checkmark {
            font-weight: 500;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        .form-group.full-width {
            grid-column: 1 / -1;
        }
        
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: 500;
            color: #34495e;
            font-size: 0.9rem;
        }
        
        input, select {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e1e8ed;
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
            transition: all 0.3s ease;
        }
        
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .btn {
            padding: 12px 25px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }
        
        .btn-success {
            background: linear-gradient(135deg, #27ae60, #2ecc71);
            color: white;
        }
        
        .btn-warning {
            background: linear-gradient(135deg, #f39c12, #e67e22);
            color: white;
        }
        
        .btn-danger {
            background: linear-gradient(135deg, #e74c3c, #c0392b);
            color: white;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        }
        
        .delivery-list {
            max-height: 400px;
            overflow-y: auto;
            border: 1px solid #e1e8ed;
            border-radius: 8px;
            padding: 15px;
            background: #f8f9fa;
        }
        
        .delivery-item {
            background: white;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 10px;
            border-left: 4px solid #667eea;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .delivery-id {
            font-weight: 600;
            color: #667eea;
            margin-bottom: 5px;
        }
        
        .delivery-details {
            font-size: 0.9rem;
            color: #7f8c8d;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        
        .stat-item {
            text-align: center;
            padding: 15px;
            background: rgba(102, 126, 234, 0.1);
            border-radius: 8px;
        }
        
        .stat-number {
            font-size: 1.5rem;
            font-weight: 700;
            color: #667eea;
            margin-bottom: 5px;
        }
        
        .stat-label {
            font-size: 0.8rem;
            color: #7f8c8d;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .action-buttons {
            display: flex;
            gap: 15px;
            margin-top: 20px;
        }
        
        .action-buttons .btn {
            flex: 1;
        }
        
        .alert {
            padding: 15px;
            border-radius: 8px;
            margin: 15px 0;
            border-left: 4px solid;
        }
        
        .alert-success {
            background: rgba(39, 174, 96, 0.1);
            border-color: #27ae60;
            color: #27ae60;
        }
        
        .alert-warning {
            background: rgba(243, 156, 18, 0.1);
            border-color: #f39c12;
            color: #f39c12;
        }

        .alert-info {
            background: rgba(52, 152, 219, 0.1);
            border-color: #3498db;
            color: #3498db;
        }

        .alert-error {
            background: rgba(231, 76, 60, 0.1);
            border-color: #e74c3c;
            color: #e74c3c;
        }

        /* Toggle Switch Styles */
        .collaboration-toggle {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            border-left: 4px solid #667eea;
        }

        .toggle-container {
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 10px;
        }

        .toggle-switch {
            position: relative;
            display: inline-block;
            width: 60px;
            height: 34px;
        }

        .toggle-switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: .4s;
            border-radius: 34px;
        }

        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 26px;
            width: 26px;
            left: 4px;
            bottom: 4px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }

        input:checked + .toggle-slider {
            background: linear-gradient(135deg, #667eea, #764ba2);
        }

        input:checked + .toggle-slider:before {
            transform: translateX(26px);
        }

        .toggle-labels {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }

        .toggle-label {
            font-size: 0.9rem;
            color: #7f8c8d;
            transition: all 0.3s ease;
        }

        .toggle-label.active {
            color: #667eea;
            font-weight: 600;
        }

        .toggle-description {
            margin-top: 10px;
            padding: 10px;
            background: rgba(102, 126, 234, 0.1);
            border-radius: 8px;
        }

        .toggle-description small {
            color: #666;
            line-height: 1.4;
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
    </style>
</head>
<body>
    <div class="main-container">
        <div class="header">
            <h1><i class="fas fa-route"></i> Multi-Company Optimizer</h1>
            <div class="subtitle">Multi-Company Collaborative Delivery Optimization</div>

            <div class="nav-menu">
                <a href="#" class="nav-button active">
                    <i class="fas fa-route"></i> Multi-Delivery
                </a>
            </div>
        </div>
        
        <div class="dashboard">
            <!-- Add Delivery Card -->
            <div class="card">
                <div class="card-header">
                    <div class="card-icon">
                        <i class="fas fa-plus"></i>
                    </div>
                    <div class="card-title">Add Delivery</div>
                </div>
                
                <form id="deliveryForm">
                    <div class="form-grid">
                        <!-- Basic Information -->
                        <div class="form-section">
                            <h4><i class="fas fa-info-circle"></i> Basic Information</h4>
                            <div class="form-row">
                                <div class="form-group">
                                    <label for="delivery_id">Delivery ID</label>
                                    <input type="text" id="delivery_id" name="delivery_id" placeholder="e.g., ADM_001" required>
                                </div>

                                <div class="form-group">
                                    <label for="company">Company</label>
                                    <select id="company" name="company" required>
                                        <option value="mainland_movers" selected>🏙️ Mainland Movers</option>
                                        <option value="lagoslink_couriers">⚡ LagosLink Couriers</option>
                                        <option value="ekoswift_logistics">🚀 EkoSwift Logistics</option>
                                        <option value="island_express">🏝️ Island Express</option>
                                    </select>
                                </div>
                            </div>
                        </div>

                        <!-- Location Information -->
                        <div class="form-section">
                            <h4><i class="fas fa-map-marker-alt"></i> Location Details</h4>
                            <div class="form-row">
                                <div class="form-group">
                                    <label for="destination_name">Destination Name</label>
                                    <input type="text" id="destination_name" name="destination_name" placeholder="e.g., Tejuosho Market, Yaba" required>
                                </div>

                                
                            </div>

                            <div class="form-row">
                                <div class="form-group">
                                    <label for="latitude">Latitude</label>
                                    <input type="number" id="latitude" name="latitude" step="0.0001" value="6.5244" min="6.2" max="6.7" required>
                                </div>

                                <div class="form-group">
                                    <label for="longitude">Longitude</label>
                                    <input type="number" id="longitude" name="longitude" step="0.0001" value="3.3792" min="3.1" max="3.7" required>
                                </div>
                            </div>
                        </div>

                        <!-- Package Information -->
                        <div class="form-section">
                            <h4><i class="fas fa-box"></i> Package Details</h4>
                            <div class="form-row">
                                <div class="form-group">
                                    <label for="package_weight">Weight (kg)</label>
                                    <input type="number" id="package_weight" name="package_weight" step="0.1" min="0.1" max="1000" placeholder="5.0" required>
                                </div>

                                <div class="form-group">
                                    <label for="package_size">Package Size</label>
                                    <select id="package_size" name="package_size" required>
                                        <option value="Small">📦 Small (< 2kg)</option>
                                        <option value="Medium" selected>📦 Medium (2-10kg)</option>
                                        <option value="Large">📦 Large (10-50kg)</option>
                                        <option value="Extra Large">📦 Extra Large (> 50kg)</option>
                                    </select>
                                </div>
                            </div>

                            
                        </div>

                        <!-- Delivery Requirements -->
                        <div class="form-section">
                            <h4><i class="fas fa-clock"></i> Delivery Requirements</h4>
                            <div class="form-row">
                                <div class="form-group">
                                    <label for="priority">Priority Level</label>
                                    <select id="priority" name="priority" required>
                                        <option value="Low">🟢 Low (3-5 days)</option>
                                        <option value="Medium" selected>🟡 Medium (1-2 days)</option>
                                        <option value="High">🔴 High (Same day)</option>
                                        <option value="Urgent">🚨 Urgent (< 4 hours)</option>
                                    </select>
                                </div>

                                
                            </div>

                            <div class="form-row">
                                <div class="form-group">
                                    <label for="time_start">Time Window Start</label>
                                    <input type="time" id="time_start" name="time_start" value="09:00" required>
                                </div>

                                <div class="form-group">
                                    <label for="time_end">Time Window End</label>
                                    <input type="time" id="time_end" name="time_end" value="17:00" required>
                                </div>
                            </div>

                            <div class="form-row">
                                <div class="form-group">
                                    <label for="delivery_date">Preferred Date</label>
                                    <input type="date" id="delivery_date" name="delivery_date" min="" required>
                                </div>

                                         </div>
                        </div>
   </div>
                    
                    <div class="action-buttons">
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-plus"></i> Add Delivery
                        </button>
                    </div>
                </form>
            </div>
            
            <!-- Current Deliveries Card -->
            <div class="card">
                <div class="card-header">
                    <div class="card-icon">
                        <i class="fas fa-list"></i>
                    </div>
                    <div class="card-title">Current Deliveries</div>
                </div>
                
                <div id="deliveryList" class="delivery-list">
                    <div style="text-align: center; color: #7f8c8d; padding: 20px;">
                        <i class="fas fa-inbox" style="font-size: 2rem; margin-bottom: 10px;"></i>
                        <div>No deliveries added yet</div>
                    </div>
                </div>
                
                <div class="action-buttons">
                    <button type="button" onclick="clearDeliveries()" class="btn btn-danger">
                        <i class="fas fa-trash"></i> Clear All
                    </button>
                </div>
            </div>
            
            <!-- Optimization Card -->
            <div class="card">
                <div class="card-header">
                    <div class="card-icon">
                        <i class="fas fa-magic"></i>
                    </div>
                    <div class="card-title">Route Optimization</div>
                </div>
                
                <div class="stats-grid">
                    <div class="stat-item">
                        <div class="stat-number" id="totalDeliveries">0</div>
                        <div class="stat-label">Deliveries</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-number" id="totalWeight">0</div>
                        <div class="stat-label">Total KG</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-number" id="highPriority">0</div>
                        <div class="stat-label">High Priority</div>
                    </div>
                </div>

                <!-- Collaboration Toggle -->
                <div class="collaboration-toggle" style="margin: 20px 0;">
                    <h4 style="margin-bottom: 15px; color: #2c3e50; display: flex; align-items: center; gap: 8px;">
                        <i class="fas fa-handshake"></i> Optimization Mode
                    </h4>
                    <div class="toggle-container">
                        <label class="toggle-switch">
                            <input type="checkbox" id="collaborationToggle" checked>
                            <span class="toggle-slider"></span>
                        </label>
                        <div class="toggle-labels">
                            <span class="toggle-label" id="individualLabel">Individual Routes</span>
                            <span class="toggle-label active" id="collaborationLabel">🤝 Collaboration Mode</span>
                        </div>
                    </div>
                    <div class="toggle-description">
                        <small id="toggleDescription">
                            <strong>Collaboration Mode:</strong> Uses clustering and cross-company collaboration with hand-off points for optimal efficiency.
                        </small>
                    </div>
                </div>
                
                <div class="action-buttons">
                    <button onclick="optimizeRoutes()" class="btn btn-success" id="optimizeBtn" disabled>
                        <i class="fas fa-route"></i> Optimize Routes
                    </button>
                </div>
                
                <div id="optimizationResult" style="margin-top: 20px;"></div>
            </div>
        </div>
    </div>
    
    <script>
        let deliveries = [];
        
        document.getElementById('deliveryForm').addEventListener('submit', function(e) {
            e.preventDefault();
            addDelivery();
        });
        
        function addDelivery() {
            const formData = new FormData(document.getElementById('deliveryForm'));
            const delivery = {
                // Basic Information
                id: formData.get('delivery_id'),
                company: formData.get('company'),

                // Location Details
                destination_name: formData.get('destination_name'),
                destination_type: formData.get('destination_type'),
                lat: parseFloat(formData.get('latitude')),
                lon: parseFloat(formData.get('longitude')),
                address: formData.get('address'),

                // Package Details
                package_weight: parseFloat(formData.get('package_weight')),
                package_size: formData.get('package_size'),
                package_type: formData.get('package_type'),
                package_value: parseFloat(formData.get('package_value')) || 0,

                // Delivery Requirements
                priority: formData.get('priority'),
                service_type: formData.get('service_type'),
                time_window_start: formData.get('time_start'),
                time_window_end: formData.get('time_end'),
                delivery_date: formData.get('delivery_date'),
                flexible_time: formData.get('flexible_time'),

                // Customer Details
                customer_name: formData.get('customer_name'),
                customer_phone: formData.get('customer_phone'),
                customer_email: formData.get('customer_email'),
                customer_type: formData.get('customer_type'),

                // Special Requirements
                vehicle_preference: formData.get('vehicle_preference'),
                insurance_required: formData.get('insurance_required'),
                special_instructions: formData.get('special_instructions'),
                signature_required: formData.get('signature_required') === 'on',
                photo_proof: formData.get('photo_proof') === 'on'
            };

            console.log('Adding delivery:', delivery);

            // Send to server
            fetch('/add_delivery', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(delivery)
            })
            .then(response => response.json())
            .then(data => {
                console.log('Server response:', data);
                if (data.success) {
                    deliveries.push(delivery);
                    updateDeliveryList();
                    updateStats();
                    document.getElementById('deliveryForm').reset();

                    // Generate new ID
                    document.getElementById('delivery_id').value = 'DEL_' + String(deliveries.length + 1).padStart(3, '0');

                    // Show success message
                    showMessage(`✅ Delivery ${delivery.id} added successfully! Total: ${data.total_deliveries}`, 'success');
                } else {
                    showMessage(`❌ Error: ${data.error}`, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showMessage(`❌ Network error: ${error.message}`, 'error');
            });
        }
        
        function updateDeliveryList() {
            const listElement = document.getElementById('deliveryList');
            
            if (deliveries.length === 0) {
                listElement.innerHTML = `
                    <div style="text-align: center; color: #7f8c8d; padding: 20px;">
                        <i class="fas fa-inbox" style="font-size: 2rem; margin-bottom: 10px;"></i>
                        <div>No deliveries added yet</div>
                    </div>
                `;
                return;
            }
            
            listElement.innerHTML = deliveries.map((delivery, idx) => `
                <div class="delivery-item">
                    <div class="delivery-id">${delivery.id}</div>
                    <div class="delivery-details">
                        📍 ${delivery.lat.toFixed(4)}, ${delivery.lon.toFixed(4)} | 
                        📦 ${delivery.package_weight}kg (${delivery.package_size}) | 
                        🚨 ${delivery.priority} Priority
                    </div>
                </div>
            `).join('');
            // Append per-delivery remove buttons
            try {
                const items = listElement.querySelectorAll('.delivery-item');
                items.forEach((item, idx) => {
                    const id = (deliveries[idx] && deliveries[idx].id) ? deliveries[idx].id : null;
                    if (!id) return;
                    const btn = document.createElement('button');
                    btn.className = 'btn btn-danger';
                    btn.type = 'button';
                    btn.style.padding = '6px 10px';
                    btn.style.fontSize = '0.85rem';
                    btn.innerHTML = '<i class="fas fa-times"></i> Remove';
                    btn.addEventListener('click', () => removeDeliveryStrict(id));
                    item.appendChild(btn);
                });
            } catch (e) { console.warn('Could not append remove buttons', e); }
        }
        
        function updateStats() {
            document.getElementById('totalDeliveries').textContent = deliveries.length;
            document.getElementById('totalWeight').textContent = deliveries.reduce((sum, d) => sum + d.package_weight, 0).toFixed(1);
            document.getElementById('highPriority').textContent = deliveries.filter(d => d.priority === 'High').length;
            
            document.getElementById('optimizeBtn').disabled = deliveries.length < 1;
        }
        
        function clearDeliveries() {
            if (deliveries.length === 0) {
                showMessage('ℹ️ No deliveries to clear', 'info');
                return;
            }

            if (confirm(`Are you sure you want to clear all ${deliveries.length} deliveries?`)) {
                fetch('/clear_deliveries', {method: 'POST'})
                .then(response => response.json())
                .then(data => {
                    if (data && data.success) {
                        deliveries = [];
                        updateDeliveryList();
                        updateStats();
                        document.getElementById('optimizationResult').innerHTML = '';
                        showMessage('✅ All deliveries cleared successfully', 'success');
                    }
                })
                .catch(error => {
                    showMessage(`❌ Error clearing deliveries: ${error.message}`, 'error');
                });
            }
        }

        function removeDelivery(deliveryId) {
            if (!deliveryId) return;
            // Find locally
            const d = deliveries.find(d => d.id === deliveryId);
            if (!d) {
                // Not in local list; still try backend removal to keep server in sync
                fetch('/remove_delivery', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: deliveryId })
                }).finally(() => {
                    updateDeliveryList();
                    updateStats();
                });
                return;
            }

            if (!confirm(`Remove delivery ${deliveryId}?`)) return;

            fetch('/remove_delivery', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: deliveryId })
            })
            .then(r => r.json())
            .then(data => {
                deliveries = deliveries.filter(x => x.id !== deliveryId);
                updateDeliveryList();
                updateStats();
                if (data && data.success) {
                    showMessage(`�o. Removed ${deliveryId}`, 'success');
                } else {
                    showMessage(`�?O Removed locally, backend sync failed`, 'warning');
                }
            })
            .catch(err => {
                deliveries = deliveries.filter(x => x.id !== deliveryId);
                updateDeliveryList();
                updateStats();
                showMessage(`�?O Removed locally. Network error: ${err.message}`,'warning');
            });
        }

        // More robust remover: normalize id, optimistically update UI, always sync server
        function removeDeliveryStrict(deliveryId) {
            const removeId = String(deliveryId || '').trim();
            if (!removeId) return;
            if (!confirm(`Remove delivery ${removeId}?`)) return;

            // Optimistic removal from UI list
            const beforeLen = deliveries.length;
            deliveries = deliveries.filter(x => String((x && x.id) || '').trim() !== removeId);
            if (deliveries.length !== beforeLen) {
                updateDeliveryList();
                updateStats();
            }
            // Always clear stale optimization results after any removal
            const res = document.getElementById('optimizationResult');
            if (res) {
                res.innerHTML = '';
                try { showMessage('Routes cleared after removal. Re-run Optimize to refresh.', 'info'); } catch (e) {}
            }

            // Keep server in sync regardless of UI state
            fetch('/remove_delivery', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: removeId })
            })
            .then(r => r.json())
            .then(data => {
                if (data && data.success) {
                    showMessage(`Removed ${removeId}`, 'success');
                } else {
                    showMessage(`Removed locally, backend sync failed`, 'warning');
                }
            })
            .catch(err => {
                showMessage(`Removed locally. Network error: ${err.message}`,'warning');
            });
        }

        function showMessage(message, type = 'info') {
            // Remove existing messages
            const existingMessages = document.querySelectorAll('.message');
            existingMessages.forEach(msg => msg.remove());

            // Create message element
            const messageDiv = document.createElement('div');
            messageDiv.className = `message alert alert-${type}`;
            messageDiv.innerHTML = message;
            messageDiv.style.position = 'fixed';
            messageDiv.style.top = '20px';
            messageDiv.style.right = '20px';
            messageDiv.style.zIndex = '1000';
            messageDiv.style.maxWidth = '400px';
            messageDiv.style.animation = 'slideIn 0.3s ease';

            document.body.appendChild(messageDiv);

            // Auto remove after 5 seconds
            setTimeout(() => {
                if (messageDiv.parentNode) {
                    messageDiv.style.animation = 'slideOut 0.3s ease';
                    setTimeout(() => messageDiv.remove(), 300);
                }
            }, 5000);
        }
        
        function optimizeRoutes() {
            console.log('Starting optimization...');
            document.getElementById('optimizeBtn').disabled = true;
            document.getElementById('optimizeBtn').innerHTML = '<i class="fas fa-spinner fa-spin"></i> Optimizing...';

            // Get collaboration mode from toggle
            const useCollaboration = document.getElementById('collaborationToggle').checked;
            console.log('Collaboration mode:', useCollaboration);

            fetch('/optimize_routes', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({use_collaboration: useCollaboration})
            })
            .then(response => response.json())
            .then(data => {
                console.log('Optimization response:', data);
                if (data.success) {
                    displayOptimizationResults(data.results, data.collaboration_mode);
                    const mode = data.collaboration_mode ? 'Collaboration' : 'Individual';
                    showMessage(`✅ ${mode} route optimization completed successfully!`, 'success');
                } else {
                    showMessage(`❌ Optimization failed: ${data.error}`, 'error');
                }
                document.getElementById('optimizeBtn').disabled = false;
                document.getElementById('optimizeBtn').innerHTML = '<i class="fas fa-route"></i> Optimize Routes';
            })
            .catch(error => {
                console.error('Optimization error:', error);
                showMessage(`❌ Network error: ${error.message}`, 'error');
                document.getElementById('optimizeBtn').disabled = false;
                document.getElementById('optimizeBtn').innerHTML = '<i class="fas fa-route"></i> Optimize Routes';
            });
        }
        
        function displayOptimizationResults(results, collaborationMode = true) {
            const resultElement = document.getElementById('optimizationResult');
            
            // Build collaboration-specific stats
            let collaborationStats = '';
            if (collaborationMode && results.collaboration_enabled) {
                collaborationStats = `
                    <div style="background: rgba(102, 126, 234, 0.1); padding: 15px; border-radius: 8px; margin-top: 15px;">
                        <strong>🤝 Collaboration Benefits:</strong><br>
                        📊 ${results.clusters_found} delivery clusters found<br>
                        🔄 ${results.collaboration_opportunities} collaboration opportunities<br>
                        💾 ${results.estimated_savings_km.toFixed(1)} km potential savings<br>
                        🚛 ${results.collaboration_routes || 0} collaboration routes + ${results.individual_routes || 0} individual routes
                    </div>
                `;
            }
            
            const modeIcon = collaborationMode ? '🤝' : '🏢';
            const modeText = collaborationMode ? 'Collaboration Mode' : 'Individual Company Mode';
            
            // Build TSP optimization steps
            let tspSteps = '';
            if (results.optimization_steps && results.optimization_steps.length > 0) {
                tspSteps = `
                    <div style="background: rgba(255, 193, 7, 0.1); padding: 15px; border-radius: 8px; margin-top: 15px; border-left: 4px solid #ffc107;">
                        <strong>🔄 TSP Optimization Steps:</strong><br>
                        <div style="max-height: 200px; overflow-y: auto; margin-top: 10px;">
                `;

                results.optimization_steps.forEach(step => {
                    tspSteps += `<div style="margin-bottom: 10px; padding: 8px; background: white; border-radius: 5px; border: 1px solid #dee2e6;">
                        <strong>${step.route_id}:</strong> ${step.swaps_made.length} swaps made<br>
                        <small style="color: #666;">Algorithm: ${step.algorithm} | Deliveries: ${step.deliveries.join(', ')}</small>`;

                    if (step.swaps_made.length > 0) {
                        tspSteps += `<br><small style="color: #28a745;">Last swap: ${step.swaps_made[step.swaps_made.length-1].swap_type} improved by ${step.swaps_made[step.swaps_made.length-1].distance_improvement.toFixed(2)}km</small>`;
                    }
                    tspSteps += `</div>`;
                });

                tspSteps += `</div></div>`;
            }

            resultElement.innerHTML = `
                <div class="alert alert-success">
                    <strong>✅ ${modeIcon} ${modeText} Optimization Complete!</strong><br>
                    🚚 ${results.total_routes} routes created<br>
                    📏 ${results.total_distance_km} km total distance<br>
                    ⏱️ ${results.total_time_minutes.toFixed(1)} minutes total time<br>
                    💰 ₦${results.total_cost_naira.toFixed(2)} total cost<br>
                    📈 ${results.average_deliveries_per_route.toFixed(1)} avg deliveries per route
                    ${collaborationStats}
                    ${tspSteps}
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px;">
                    <button onclick="window.open('/map', '_blank')" class="btn btn-success">
                        <i class="fas fa-map-marked-alt"></i> View Map
                    </button>
                    <button onclick="window.open('/results', '_blank')" class="btn btn-primary">
                        <i class="fas fa-list-alt"></i> Detailed Results
                    </button>
                </div>
            `;
        }
        
        // Initialize form with enhanced features
        document.getElementById('delivery_id').value = 'DEL_001';

        // Set today's date as minimum and default for delivery date
        const today = new Date().toISOString().split('T')[0];
        const deliveryDateInput = document.getElementById('delivery_date');
        deliveryDateInput.min = today;
        deliveryDateInput.value = today;

        // Lagos State location suggestions
        const lagosLocations = {
            'Ikeja Computer Village': { lat: 6.4450, lon: 3.4700, type: 'Commercial' },
            'Yaba Tejuosho Market': { lat: 65195, lon: 3.3700, type: 'Commercial' },
            'Victoria Island': { lat: 6.4582, lon: 3.3606, type: 'Commercial' },
            'Lekki Phase 1': { lat: 6.4400, lon: 3.4900, type: 'Residential' },
            'Surulere Stadium': { lat: 6.4531, lon: 3.3958, type: 'Commercial' },
            'Ojota Bus Terminal': { lat: 6.4863, lon: 3.3606, type: 'Commercial' },
            'Ikeja City Mall': { lat: 6.6018, lon: 3.3515, type: 'Commercial' },
            'CMS Marina': { lat: 6.4531, lon: 3.3958, type: 'Government' },
            'Ikoyi': { lat: 6.4510, lon: 3.4281, type: 'Residential' },
            'Ajah Market': { lat: 6.4698, lon: 3.5852, type: 'Commercial' }
        };

        // Add location suggestions functionality
        const destinationInput = document.getElementById('destination_name');
        const latInput = document.getElementById('latitude');
        const lonInput = document.getElementById('longitude');
        const destTypeSelect = document.getElementById('destination_type');

        // Create datalist for location suggestions
        const datalist = document.createElement('datalist');
        datalist.id = 'location-suggestions';
        Object.keys(lagosLocations).forEach(location => {
            const option = document.createElement('option');
            option.value = location;
            datalist.appendChild(option);
        });
        document.body.appendChild(datalist);
        destinationInput.setAttribute('list', 'location-suggestions');

        // Auto-fill coordinates when location is selected
        destinationInput.addEventListener('input', function() {
            const selectedLocation = this.value;
            if (lagosLocations[selectedLocation]) {
                const location = lagosLocations[selectedLocation];
                latInput.value = location.lat;
                lonInput.value = location.lon;
                destTypeSelect.value = location.type;
            }
        });

        // Auto-generate delivery ID
        let deliveryCounter = 1;
        function generateDeliveryId() {
            const company = document.getElementById('company').value;
            const prefix = {
                'mainland_movers': 'MM',
                'lagoslink_couriers': 'LLC',
                'ekoswift_logistics': 'ESL',
                'island_express': 'IX'
            }[company] || 'DEL';

            return `${prefix}_${String(deliveryCounter++).padStart(3, '0')}`;
        }

        // Update delivery ID when company changes
        document.getElementById('company').addEventListener('change', function() {
            document.getElementById('delivery_id').value = generateDeliveryId();
        });

        // Form validation enhancements
        document.getElementById('deliveryForm').addEventListener('submit', function(e) {
            const weight = parseFloat(document.getElementById('package_weight').value);
            const size = document.getElementById('package_size').value;

            // Validate weight vs size consistency
            if (size === 'Small' && weight > 2) {
                alert('⚠️ Package weight seems too high for Small size. Please verify.');
                e.preventDefault();
                return;
            }
            if (size === 'Medium' && (weight < 2 || weight > 10)) {
                alert('⚠️ Package weight should be between 2-10kg for Medium size.');
                e.preventDefault();
                return;
            }
            if (size === 'Large' && (weight < 10 || weight > 50)) {
                alert('⚠️ Package weight should be between 10-50kg for Large size.');
                e.preventDefault();
                return;
            }
            if (size === 'Extra Large' && weight < 50) {
                alert('⚠️ Package weight should be over 50kg for Extra Large size.');
                e.preventDefault();
                return;
            }
        });

        // Phone number formatting
        document.getElementById('customer_phone').addEventListener('input', function() {
            let value = this.value.replace(/\\D/g, '');
            if (value.startsWith('234')) {
                value = '+' + value;
            } else if (value.startsWith('0')) {
                value = '+234' + value.substring(1);
            } else if (value.length > 0 && !value.startsWith('+')) {
                value = '+234' + value;
            }
            this.value = value;
        });

        // Initialize collaboration toggle
        function initializeCollaborationToggle() {
            const toggle = document.getElementById('collaborationToggle');
            const individualLabel = document.getElementById('individualLabel');
            const collaborationLabel = document.getElementById('collaborationLabel');
            const description = document.getElementById('toggleDescription');
            
            function updateToggleState() {
                if (toggle.checked) {
                    // Collaboration mode
                    individualLabel.classList.remove('active');
                    collaborationLabel.classList.add('active');
                    description.innerHTML = `
                        <strong>🤝 Collaboration Mode:</strong> Uses clustering and cross-company collaboration with hand-off points for optimal efficiency and cost savings.
                    `;
                } else {
                    // Individual mode
                    individualLabel.classList.add('active');
                    collaborationLabel.classList.remove('active');
                    description.innerHTML = `
                        <strong>🏢 Individual Mode:</strong> Each company optimizes routes independently without collaboration or resource sharing.
                    `;
                }
            }
            
            // Set initial state
            updateToggleState();
            
            // Add event listener
            toggle.addEventListener('change', updateToggleState);
        }
        
        // Initialize toggle on page load
        initializeCollaborationToggle();
    </script>
</body>
</html>
        """
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html_content.encode())
    
    def handle_add_delivery(self):
        """Handle adding a delivery"""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            delivery_data = json.loads(post_data)

            print(f"[ADD] Adding delivery: {delivery_data['id']} - multi_delivery_app.py:1277")
            # Lazy initialize optimizer if not loaded
            if self.optimizer is None:
                try:
                    from multi_delivery_optimizer import MultiDeliveryOptimizer as _MDO
                    global global_optimizer, MODEL_STATUS
                    global_optimizer = _MDO()
                    self.optimizer = global_optimizer
                    MODEL_STATUS = {"loaded": True, "error": None}
                    print("[INIT] Optimizer lazily initialized - multi_delivery_app.py:1286")
                except Exception as init_err:
                    print(f"[WARN] Lazy init failed: {init_err} - multi_delivery_app.py:1288")
            if self.optimizer is None:
                # Fallback in-memory when model unavailable
                FALLBACK_DELIVERIES.append(delivery_data)
            else:
                self.optimizer.add_delivery(delivery_data)

            print(f"📊 Total deliveries now: {len(self.optimizer.deliveries)} - multi_delivery_app.py:1295")

            response = {
                'success': True,
                'message': 'Delivery added successfully',
                'total_deliveries': (len(self.optimizer.deliveries) if self.optimizer else len(FALLBACK_DELIVERIES))
            }

        except Exception as e:
            print(f"[ERROR] Error adding delivery: {e} - multi_delivery_app.py:1304")
            response = {'success': False, 'error': str(e)}

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())
    
    def handle_optimize_routes(self):
        """Handle route optimization"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = {}
            if content_length > 0:
                post_body = self.rfile.read(content_length).decode('utf-8')
                try:
                    post_data = json.loads(post_body)
                except:
                    pass
            
            use_collaboration = post_data.get('use_collaboration', True)
            print(f"[OPTIMIZE] Starting optimization with {len(self.optimizer.deliveries) if self.optimizer else 0} deliveries (collaboration: {use_collaboration}) - multi_delivery_app.py:1325")

            if self.optimizer is None:
                # Try lazy init again at optimize time
                try:
                    from multi_delivery_optimizer import MultiDeliveryOptimizer as _MDO
                    global global_optimizer, MODEL_STATUS
                    global_optimizer = _MDO()
                    self.optimizer = global_optimizer
                    MODEL_STATUS = {"loaded": True, "error": None}
                    print("[INIT] Optimizer lazily initialized for optimization - multi_delivery_app.py:1335")
                except Exception as init_err:
                    print(f"[WARN] Lazy init (optimize) failed: {init_err} - multi_delivery_app.py:1337")
            if self.optimizer is None:
                response = {'success': False, 'error': 'Model not loaded. Ensure artifacts exist in models/'}
            elif len(self.optimizer.deliveries) == 0:
                response = {'success': False, 'error': 'No deliveries to optimize. Please add deliveries first.'}
            else:
                routes = self.optimizer.create_optimized_routes(use_collaboration=use_collaboration)
                results = self.optimizer.optimization_results
                variants = getattr(self.optimizer, 'route_plan_variants', [routes])

                print(f"[SUCCESS] Optimization complete: {len(routes)} routes created - multi_delivery_app.py:1347")
                response = {'success': True, 'results': results, 'routes': routes, 'route_variants': variants, 'collaboration_mode': use_collaboration}

        except Exception as e:
            print(f"[ERROR] Optimization error: {e} - multi_delivery_app.py:1351")
            import traceback
            traceback.print_exc()
            response = {'success': False, 'error': str(e)}

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())
    
    def handle_clear_deliveries(self):
        """Handle clearing all deliveries"""
        try:
            if not self.optimizer:
                cleared = len(FALLBACK_DELIVERIES)
                FALLBACK_DELIVERIES.clear()
                print(f"[CLEAR] Optimizer not loaded; cleared {cleared} fallback deliveries - multi_delivery_app.py:1367")
                response = {'success': True, 'message': 'Cleared (no optimizer)', 'cleared': cleared}
            else:
                print(f"[CLEAR] Clearing {len(self.optimizer.deliveries)} deliveries  handle_clear_deliveries - multi_delivery_app.py:1370")
                # Use optimizer's dedicated clear to ensure all dependent state is reset
                try:
                    self.optimizer.clear_deliveries()
                except AttributeError:
                    # Backward compatibility if method is missing
                    self.optimizer.deliveries = []
                    self.optimizer.original_deliveries = []
                    self.optimizer.optimized_routes = []
                    self.optimizer.individual_routes = []
                    self.optimizer.collaboration_routes = []
                    self.optimizer.collaboration_handoffs = []
                    self.optimizer.optimization_results = {}
                print("All deliveries cleared  handle_clear_deliveries - multi_delivery_app.py:1383")
                response = {'success': True, 'message': 'All deliveries cleared'}
        except Exception as e:
            print(f"[ERROR] Clear failed: {e} - multi_delivery_app.py:1386")
            response = {'success': False, 'error': str(e)}

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def handle_remove_delivery(self):
        """Remove a single delivery by id"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
            data = json.loads(body or '{}')
            delivery_id = str(data.get('id', '')).strip()
            if not delivery_id:
                raise ValueError('Missing delivery id')

            if not self.optimizer:
                # If optimizer not loaded, remove from fallback store
                before = len(FALLBACK_DELIVERIES)
                remaining = [d for d in FALLBACK_DELIVERIES if str(d.get('id')) != delivery_id]
                removed = before - len(remaining)
                if removed:
                    FALLBACK_DELIVERIES[:] = remaining
                print(f"[REMOVE:FALLBACK] id={delivery_id} removed={removed} remaining={len(FALLBACK_DELIVERIES)} - multi_delivery_app.py:1411")
                response = {'success': True, 'message': 'Removed (no optimizer)', 'id': delivery_id, 'removed': removed, 'remaining': len(FALLBACK_DELIVERIES)}
            else:
                before = len(self.optimizer.deliveries)
                self.optimizer.deliveries = [d for d in self.optimizer.deliveries if str(d.get('id')) != delivery_id]
                self.optimizer.original_deliveries = [d for d in self.optimizer.original_deliveries if str(d.get('id')) != delivery_id]
                # Clear any cached routes as they may be stale
                self.optimizer.optimized_routes = []
                self.optimizer.individual_routes = []
                self.optimizer.collaboration_routes = []
                self.optimizer.collaboration_handoffs = []
                self.optimizer.optimization_results = {}
                after = len(self.optimizer.deliveries)
                removed = before - after
                print(f"[REMOVE] id={delivery_id} removed={removed} remaining={after} - multi_delivery_app.py:1425")
                response = {'success': True, 'removed': removed, 'remaining': after, 'id': delivery_id}
        except Exception as e:
            print(f"[ERROR] Remove failed: {e} - multi_delivery_app.py:1428")
            response = {'success': False, 'error': str(e)}

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def serve_status(self):
        """Serve current status of deliveries"""
        if self.optimizer:
            total = len(self.optimizer.deliveries)
            deliveries_list = [{'id': d.get('id'), 'priority': d.get('priority')} for d in self.optimizer.deliveries]
            has_routes = len(self.optimizer.optimized_routes) > 0
            total_routes = len(self.optimizer.optimized_routes)
        else:
            total = len(FALLBACK_DELIVERIES)
            deliveries_list = [{'id': d.get('id'), 'priority': d.get('priority')} for d in FALLBACK_DELIVERIES]
            has_routes = False
            total_routes = 0

        status = {
            'model_loaded': MODEL_STATUS.get('loaded', False) if 'MODEL_STATUS' in globals() else (self.optimizer is not None),
            'model_error': MODEL_STATUS.get('error') if 'MODEL_STATUS' in globals() else None,
            'total_deliveries': total,
            'deliveries': deliveries_list,
            'has_routes': has_routes,
            'total_routes': total_routes
        }

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(status).encode())

    def serve_map_page(self):
        """Serve the enhanced map visualization page with warehouses and collaboration"""
        # Parse URL parameters
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        route_type = query_params.get('type', ['collaboration'])[0]  # Default to collaboration
        # Variant selection (1-based in URL for readability)
        try:
            variant_index = max(0, int(query_params.get('variant', ['1'])[0]) - 1)
        except Exception:
            variant_index = 0
        
        # Get visualization data from optimizer
        if self.optimizer and hasattr(self.optimizer, 'get_route_visualization_data'):
            viz_data = self.optimizer.get_route_visualization_data(route_type)
            if route_type == 'collaboration':
                route_variants = viz_data.get('route_variants', []) or [viz_data.get('routes', [])]
            else:
                route_variants = [viz_data.get('routes', [])]
            # Clamp variant index
            if variant_index >= len(route_variants):
                variant_index = 0
            routes_data = route_variants[variant_index]
            warehouses_data = []
            collaboration_data = []

            # Get all warehouses from the collaboration network
            for company_id, company_info in self.optimizer.companies.items():
                company_color = self.get_company_color(company_id)
                for warehouse in company_info['warehouses']:
                    warehouses_data.append({
                        'name': warehouse['name'],
                        'lat': warehouse['lat'],
                        'lon': warehouse['lon'],
                        'company': company_info['name'],
                        'company_id': company_id,
                        'capacity': warehouse.get('capacity', 500),
                        'color': company_color,
                        'specialties': warehouse.get('specialties', []),
                        'vehicle_fleet': warehouse.get('vehicle_fleet', {}),
                        'operating_hours': warehouse.get('operating_hours', '08:00-18:00')
                    })

            # Get handoffs for collaboration visualization
            handoffs = viz_data.get('handoffs', [])
            for handoff in handoffs:
                collaboration_data.append({
                    'name': f"Handoff {handoff['from_company']}→{handoff['to_company']}",
                    'lat': handoff['location'][0],
                    'lon': handoff['location'][1],
                    'companies': [handoff['from_company'], handoff['to_company']],
                    'warehouses': [],  # Not applicable for handoffs
                    'capacity': len(handoff.get('orders_transferred', [])),
                    'fee': 0,  # No fee for handoffs
                    'processing_time': 0,  # Instant handoff
                    'type': 'handoff'
                })

            # Get exchange points for collaboration visualization
            if hasattr(self.optimizer, 'exchange_points'):
                for exchange in self.optimizer.exchange_points:
                    collaboration_data.append({
                        'name': exchange['name'],
                        'lat': exchange['location']['lat'],
                        'lon': exchange['location']['lon'],
                        'companies': exchange['companies'],
                        'warehouses': exchange['warehouses'],
                        'capacity': exchange.get('capacity', 100),
                        'fee': exchange.get('exchange_fee', 50),
                        'processing_time': exchange.get('processing_time', 30)
                    })

            # Process routes for visualization
            processed_routes = []
            # Company -> color palette (distinct, high-contrast)
            route_colors = {
                'mainland_movers': '#e74c3c',   # red
                'lagoslink_couriers': '#3498db',# blue
                'ekoswift_logistics': '#2ecc71',# green
                'island_express': '#f39c12'     # orange
            }

            for route in routes_data:
                if route.get('type') == 'collaboration':
                    # Handle collaboration routes
                    company_id = route.get('handling_company', 'mainland_movers')
                    # Color collaboration route by handling company for consistency
                    color = route_colors.get(company_id, '#ff6b6b')

                    # Build route points from coordinates if available
                    if 'coordinates' in route:
                        route_points = []
                        for i, coord in enumerate(route['coordinates']):
                            if i == 0 or i == len(route['coordinates']) - 1:
                                # Depot points
                                route_points.append({
                                    'lat': coord[0], 'lon': coord[1], 'name': 'Depot',
                                    'type': 'depot'
                                })
                            elif i == 1 and route.get('handoff_point'):
                                # Handoff point
                                handoff = route['handoff_point']
                                route_points.append({
                                    'lat': handoff.get('lat'), 'lon': handoff.get('lon'),
                                    'name': handoff.get('name', 'Handoff'), 'type': 'handoff'
                                })
                            else:
                                # Delivery points
                                delivery_idx = i - 2  # Adjust for depot and handoff
                                if delivery_idx < len(route['deliveries']):
                                    delivery = route['deliveries'][delivery_idx]
                                    route_points.append({
                                        'lat': delivery['lat'], 'lon': delivery['lon'],
                                        'name': delivery['id'], 'type': 'delivery',
                                        'company': delivery.get('company', company_id),
                                        'weight': delivery.get('package_weight', 0),
                                        'priority': delivery.get('priority', 'Medium')
                                    })
                    else:
                        route_points = []

                    processed_routes.append({
                        'id': route['route_id'],
                        'type': 'collaboration',
                        'company_id': company_id,
                        'company_name': f"Collaboration ({route.get('handling_company', 'Unknown')})",
                        'color': color,
                        'vehicle': 'Mixed',
                        'points': route_points,
                        'stats': {
                            'deliveries': route.get('total_deliveries', 0),
                            'distance': route.get('total_distance_km', 0),
                            'time': route.get('total_time_minutes', 0),
                            'cost': route.get('total_cost_naira', 0),
                            'efficiency': route.get('collaboration_score', 85),
                            'savings': route.get('collaboration_savings_km', 0)
                        }
                    })
                elif route.get('type') == 'handoff':
                    # Handle handoff routes
                    company_id = route.get('company_id', 'mainland_movers')
                    color = route_colors.get(company_id, '#9b59b6')

                    # Build route points for handoff routes
                    route_points = []
                    if 'coordinates' in route:
                        for i, coord in enumerate(route['coordinates']):
                            if i == 0 or i == len(route['coordinates']) - 1:
                                route_points.append({
                                    'lat': coord[0], 'lon': coord[1], 'name': 'Depot',
                                    'type': 'depot'
                                })
                            elif i == 1 and route.get('handoff_point'):
                                # Handoff point
                                handoff = route['handoff_point']
                                route_points.append({
                                    'lat': handoff.get('lat'), 'lon': handoff.get('lon'),
                                    'name': handoff.get('name', 'Handoff'), 'type': 'handoff'
                                })

                    processed_routes.append({
                        'id': route['route_id'],
                        'type': 'handoff',
                        'company_id': company_id,
                        'company_name': f"{self.optimizer.companies.get(company_id, {}).get('name', 'Unknown')} (Handoff)",
                        'color': color,
                        'vehicle': 'van',  # Standard vehicle for handoff
                        'points': route_points,
                        'stats': {
                            'deliveries': route.get('total_deliveries', 0),
                            'distance': route.get('total_distance_km', 0),
                            'time': route.get('total_time_minutes', 0),
                            'cost': route.get('total_cost_naira', 0),
                            'efficiency': route.get('efficiency_score', 80)
                        }
                    })
                else:
                    # Handle individual routes
                    company_id = route.get('company_id', 'mainland_movers')
                    color = route_colors.get(company_id, '#9b59b6')

                    # Build route points
                    route_points = []
                    if 'coordinates' in route:
                        for i, coord in enumerate(route['coordinates']):
                            if i == 0 or i == len(route['coordinates']) - 1:
                                route_points.append({
                                    'lat': coord[0], 'lon': coord[1], 'name': 'Depot',
                                    'type': 'depot'
                                })
                            else:
                                delivery_idx = i - 1
                                if delivery_idx < len(route['deliveries']):
                                    delivery = route['deliveries'][delivery_idx]
                                    route_points.append({
                                        'lat': delivery['lat'], 'lon': delivery['lon'],
                                        'name': delivery['id'], 'type': 'delivery',
                                        'company': delivery.get('company', company_id),
                                        'weight': delivery.get('package_weight', 0),
                                        'priority': delivery.get('priority', 'Medium')
                                    })

                    processed_routes.append({
                        'id': route['route_id'],
                        'type': 'individual',
                        'company_id': company_id,
                        'company_name': self.optimizer.companies.get(company_id, {}).get('name', 'Unknown'),
                        'color': color,
                        'vehicle': route.get('vehicle_type', 'van'),
                        'points': route_points,
                        'stats': {
                            'deliveries': route.get('total_deliveries', 0),
                            'distance': route.get('total_distance_km', 0),
                            'time': route.get('total_time_minutes', 0),
                            'cost': route.get('total_cost_naira', 0),
                            'efficiency': route.get('efficiency_score', 85)
                        }
                    })
            
            routes_data = processed_routes
        else:
            # Fallback to empty data
            routes_data = []
            warehouses_data = []
            collaboration_data = []
            route_variants = [routes_data]

        # Create and send the HTML response (outside branches)
        html_content = self.create_map_html(routes_data, warehouses_data, collaboration_data, route_type, variants_count=len(route_variants), current_variant=variant_index)

        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html_content.encode())

    def get_company_color(self, company_id):
        """Get color for company visualization"""
        colors = {
            'mainland_movers': '#e74c3c',
            'lagoslink_couriers': '#3498db',
            'ekoswift_logistics': '#2ecc71',
            'island_express': '#f39c12'
        }
        return colors.get(company_id, '#9b59b6')

    def get_company_depot(self, company_id):
        """Get main depot/warehouse for a company"""
        if company_id in self.optimizer.companies:
            main_warehouse = self.optimizer.companies[company_id]['warehouses'][0]
            return {
                'lat': main_warehouse['lat'],
                'lon': main_warehouse['lon'],
                'name': main_warehouse['name']
            }
        # Default to Lagos Central Hub
        return {'lat': 6.5244, 'lon': 3.3792, 'name': 'Lagos Central Hub'}

    def create_map_html(self, routes_data, warehouses_data, collaboration_data, route_type="collaboration", variants_count: int = 1, current_variant: int = 0):
        """Create the enhanced HTML content for the map"""
        # Convert data to JSON strings for JavaScript
        routes_json = json.dumps(routes_data)
        warehouses_json = json.dumps(warehouses_data)
        collaboration_json = json.dumps(collaboration_data)
        
        # Determine page title and mode info
        mode_title = "🤝 Collaboration View" if route_type == "collaboration" else "🏢 Individual Company View"
        mode_description = ("Cross-company collaboration with hand-off points" if route_type == "collaboration"
                          else "Individual company routes without collaboration")
        variant_label = f"Plan {current_variant+1}/{variants_count}" if variants_count and variants_count > 1 else "Plan 1/1"

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Last Mile Multi-Company Delivery Network - {variant_label}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }}

        .header {{
            text-align: center;
            padding: 20px;
            color: white;
        }}

        .header h1 {{
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 10px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }}

        .nav-menu {{
            display: flex;
            justify-content: center;
            gap: 15px;
            margin-top: 15px;
        }}

        .nav-button {{
            background: rgba(255,255,255,0.2);
            color: white;
            padding: 10px 20px;
            border-radius: 20px;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s ease;
            border: 2px solid rgba(255,255,255,0.3);
            font-size: 0.9rem;
        }}

        .nav-button:hover {{
            background: rgba(255,255,255,0.3);
            transform: translateY(-2px);
        }}

        .container {{
            display: flex;
            height: calc(100vh - 120px);
            margin: 0 20px 20px 20px;
            gap: 20px;
        }}

        .sidebar {{
            width: 350px;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 20px;
            overflow-y: auto;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
        }}

        .map-container {{
            flex: 1;
            background: white;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            position: relative;
        }}

        #map {{
            width: 100%;
            height: 100%;
        }}

        .route-legend {{
            margin-bottom: 20px;
        }}

        .route-item {{
            background: #f8f9fa;
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 15px;
            border-left: 4px solid;
        }}

        .route-header {{
            display: flex;
            justify-content: between;
            align-items: center;
            margin-bottom: 10px;
        }}

        .route-title {{
            font-weight: 600;
            font-size: 1.1rem;
        }}

        .route-vehicle {{
            background: linear-gradient(135deg, #27ae60, #2ecc71);
            color: white;
            padding: 4px 12px;
            border-radius: 15px;
            font-size: 0.8rem;
            margin-left: auto;
        }}

        .route-stats {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            font-size: 0.85rem;
            color: #666;
        }}

        .stat {{
            display: flex;
            justify-content: space-between;
        }}

        .route-toggle {{
            background: none;
            border: none;
            color: #667eea;
            cursor: pointer;
            font-size: 0.9rem;
            margin-top: 10px;
            padding: 5px 0;
        }}

        .route-toggle:hover {{
            text-decoration: underline;
        }}

        .summary-stats {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
        }}

        .summary-stats h3 {{
            margin-bottom: 15px;
            font-size: 1.2rem;
        }}

        .summary-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            font-size: 0.9rem;
        }}

        .map-controls {{
            position: absolute;
            top: 10px;
            right: 10px;
            z-index: 1000;
            display: flex;
            gap: 10px;
        }}

        .control-btn {{
            background: white;
            border: none;
            border-radius: 8px;
            padding: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            cursor: pointer;
            transition: all 0.3s ease;
        }}

        .control-btn:hover {{
            background: #f8f9fa;
            transform: translateY(-2px);
        }}

        @media (max-width: 768px) {{
            .container {{
                flex-direction: column;
                height: auto;
            }}

            .sidebar {{
                width: 100%;
                height: 300px;
            }}

            .map-container {{
                height: 400px;
            }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1><i class="fas fa-map-marked-alt"></i> {mode_title}</h1>
        <div class="subtitle">{mode_description}</div>

        <div class="nav-menu">
            <a href="/" class="nav-button">
                <i class="fas fa-arrow-left"></i> Back to Optimizer
            </a>
            <a href="/results" class="nav-button">
                <i class="fas fa-list"></i> Detailed Results
            </a>
            <button onclick="toggleViewMode()" class="nav-button" id="viewToggleBtn" style="border: none; cursor: pointer;">
                <i class="fas fa-exchange-alt"></i> Switch to {'Individual' if route_type == 'collaboration' else 'Collaboration'} View
            </button>
            
        </div>
    </div>

    <div class="container">
        <div class="sidebar">
            <div class="summary-stats">
                <h3><i class="fas fa-chart-bar"></i> Summary</h3>
                <div class="summary-grid">
                    <div>Routes: <strong>{len(routes_data)}</strong></div>
                    <div>Deliveries: <strong>{sum(route['stats']['deliveries'] for route in routes_data)}</strong></div>
                    <div>Distance: <strong>{sum(route['stats']['distance'] for route in routes_data):.1f}km</strong></div>
                    <div>Time: <strong>{sum(route['stats']['time'] for route in routes_data):.0f}min</strong></div>
                </div>
            </div>

            <div class="route-legend">
                <h3 style="margin-bottom: 15px; color: #2c3e50;"><i class="fas fa-route"></i> Routes</h3>
"""

        # Add route legend items
        for route in routes_data:
            html_content += f"""
                <div class="route-item" style="border-left-color: {route['color']};">
                    <div class="route-header">
                        <div class="route-title" style="color: {route['color']};">
                            <i class="fas fa-route"></i> {route['id']}
                        </div>
                        <div class="route-vehicle">
                            <i class="fas fa-truck"></i> {route['vehicle']}
                        </div>
                    </div>
                    <div class="route-stats">
                        <div class="stat">
                            <span>Deliveries:</span>
                            <strong>{route['stats']['deliveries']}</strong>
                        </div>
                        <div class="stat">
                            <span>Distance:</span>
                            <strong>{route['stats']['distance']:.1f}km</strong>
                        </div>
                        <div class="stat">
                            <span>Time:</span>
                            <strong>{route['stats']['time']:.0f}min</strong>
                        </div>
                        <div class="stat">
                            <span>Cost:</span>
                            <strong>₦{route['stats']['cost']:.0f}</strong>
                        </div>
                    </div>
                    <div class="route-controls">
                        <button class="route-toggle" onclick="toggleRoute('{route['id']}')">
                            <i class="fas fa-eye"></i> Toggle on Map
                        </button>
                        <button class="animate-btn" onclick="startRouteAnimation('{route['id']}')">
                            <i class="fas fa-play"></i> Animate Route
                        </button>
                        {('<button class=\"animate-btn\" onclick=\"startSwapAnimation(\'' + route['id'] + '\')\">\n                            <i class=\"fas fa-people-arrows\"></i> Swap Animation\n                        </button>' if route.get('type') == 'collaboration' else '')}
                    </div>
                </div>
            """

        html_content += f"""
            </div>
        </div>

        <div class="map-container">
            <div class="map-controls">
                    <i class=" fas fa-route\></i> Routes - {variant_label}
                    <i class="fas fa-route"></i> Routes • {variant_label}
                </button>
                <button class="control-btn" onclick="toggleWarehouses()" title="Toggle Warehouses">
                    <i class="fas fa-warehouse"></i> Warehouses
                </button>
                <button class="control-btn" onclick="toggleCollaboration()" title="Toggle Collaboration">
                    <i class="fas fa-handshake"></i> Collaboration
                </button>
                <button class="control-btn" onclick="fitMapToAll()" title="Fit to All">
                    <i class="fas fa-expand-arrows-alt"></i> Fit All
                </button>
                <button class="control-btn" onclick="showCompanyFilter()" title="Filter by Company">
                    <i class="fas fa-filter"></i> Filter
                </button>
                <button class="control-btn" onclick="animateAllRoutes()" title="Animate All Routes" style="background: linear-gradient(45deg, #ff6b6b, #4ecdc4);">
                    <i class="fas fa-play"></i> Animate
                </button>
                <button class="control-btn" onclick="stopAllAnimations()" title="Stop Animations" style="background: #e74c3c;">
                    <i class="fas fa-stop"></i> Stop
                </button>
            </div>
            <div id="map"></div>

            <!-- Company Filter Panel -->
            <div id="companyFilter" class="filter-panel" style="display: none;">
                <h3><i class="fas fa-building"></i> Company Filter</h3>
                <div class="company-checkboxes">
                    <label><input type="checkbox" value="mainland_movers" checked> 🏙️ Mainland Movers</label>
                    <label><input type="checkbox" value="lagoslink_couriers" checked> ⚡ LagosLink Couriers</label>
                    <label><input type="checkbox" value="ekoswift_logistics" checked> 🚀 EkoSwift Logistics</label>
                    <label><input type="checkbox" value="island_express" checked> 🏝️ Island Express</label>
                </div>
                <button onclick="applyCompanyFilter()" class="apply-filter-btn">Apply Filter</button>
                <button onclick="hideCompanyFilter()" class="close-filter-btn">Close</button>
            </div>
        </div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        // Data from server
        const routesData = {routes_json};
        const warehousesData = {warehouses_json};
        const collaborationData = {collaboration_json};
        const variantsCount = {variants_count};
        let currentVariant = {current_variant};
        const routeType = '{route_type}';
        const variantLabel = 'Plan ' + (currentVariant + 1) + '/' + (variantsCount || 1);
        function toggleVariant() {{
            if (variantsCount <= 1) {{ showAllRoutes(); return; }}
            const next = (currentVariant + 1) % variantsCount;
            const params = new URLSearchParams(window.location.search);
            params.set('type', '{route_type}');
            params.set('variant', String(next + 1));
            window.location.search = params.toString();
        }}

        // Ensure a working "Routes" plan toggle button is present in Collaboration view
        (function ensureVariantButton() {{
            if (routeType !== 'collaboration') return;
            const mc = document.querySelector('.map-controls');
            if (!mc) return;
            let btn = mc.querySelector('[data-variant-toggle]');
            if (!btn) {{
                btn = document.createElement('button');
                btn.className = 'control-btn';
                btn.title = 'Switch Route Plan';
                btn.setAttribute('data-variant-toggle', '1');
                btn.innerHTML = '<i class="fas fa-route"></i> Routes - ' + variantLabel;
                btn.addEventListener('click', toggleVariant);
                mc.insertBefore(btn, mc.firstChild);
            }} else {{
                btn.innerHTML = '<i class=\"fas fa-route\"></i> Routes - ' + variantLabel;
            }}
        }})();

        // Initialize map centered on Lagos State
        const map = L.map('map').setView([6.5244, 3.3792], 11);

        // Add tile layer
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '© OpenStreetMap contributors'
        }}).addTo(map);

        // Animation variables
        let routeAnimations = [];
        let exchangeAnimations = [];
        let movingMarkers = [];

        // Store layers for toggling
        const routeLayers = {{}};
        const routeGroups = {{}};
        const warehouseGroup = L.layerGroup().addTo(map);
        const collaborationGroup = L.layerGroup().addTo(map);
        const animationLayer = L.layerGroup().addTo(map);
        const exchangeLayer = L.layerGroup().addTo(map);
        let warehousesVisible = true;
        let collaborationVisible = true;

        // Add warehouse markers
        warehousesData.forEach(warehouse => {{
            const warehouseIcon = L.divIcon({{
                className: 'warehouse-marker',
                html: `<div style="background: ${{warehouse.color}}; color: white; border-radius: 8px; width: 35px; height: 35px; display: flex; align-items: center; justify-content: center; font-weight: bold; border: 3px solid white; box-shadow: 0 3px 12px rgba(0,0,0,0.4);"><i class="fas fa-warehouse" style="font-size: 14px;"></i></div>`,
                iconSize: [35, 35],
                iconAnchor: [17.5, 17.5]
            }});

            const fleetInfo = Object.entries(warehouse.vehicle_fleet || {{}}).map(([vehicle, count]) =>
                `${{vehicle}}: ${{count}}`
            ).join(', ') || 'No fleet data';

            const specialtiesInfo = warehouse.specialties && warehouse.specialties.length > 0
                ? warehouse.specialties.join(', ')
                : 'General logistics';

            const warehouseMarker = L.marker([warehouse.lat, warehouse.lon], {{icon: warehouseIcon}})
                .bindPopup(`
                    <div style="min-width: 200px;">
                        <strong>🏢 ${{warehouse.name}}</strong><br>
                        <strong>Company:</strong> ${{warehouse.company}}<br>
                        <strong>Capacity:</strong> ${{warehouse.capacity}}kg<br>
                        <strong>Hours:</strong> ${{warehouse.operating_hours}}<br>
                        <strong>Fleet:</strong> ${{fleetInfo}}<br>
                        <strong>Specialties:</strong> ${{specialtiesInfo}}
                    </div>
                `);

            warehouseGroup.addLayer(warehouseMarker);
        }});

        // Add collaboration exchange points
        collaborationData.forEach(exchange => {{
            const exchangeIcon = L.divIcon({{
                className: 'exchange-marker',
                html: '<div style="background: #f39c12; color: white; border-radius: 50%; width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; font-weight: bold; border: 3px solid white; box-shadow: 0 3px 12px rgba(0,0,0,0.4); animation: pulse 2s infinite;"><i class="fas fa-handshake" style="font-size: 12px;"></i></div>',
                iconSize: [30, 30],
                iconAnchor: [15, 15]
            }});

            const exchangeMarker = L.marker([exchange.lat, exchange.lon], {{icon: exchangeIcon}})
                .bindPopup(`
                    <div style="min-width: 250px; text-align: center;">
                        <div style="background: linear-gradient(45deg, #f39c12, #e67e22); color: white; padding: 10px; margin: -10px -10px 10px -10px; border-radius: 8px 8px 0 0;">
                            <strong>🤝 ${{exchange.name}}</strong>
                        </div>
                        <div style="text-align: left;">
                            <div style="margin: 8px 0;">
                                <strong>🏢 Companies (${{exchange.companies.length}}):</strong><br>
                                <small style="color: #666;">${{exchange.companies.join(' • ')}}</small>
                            </div>
                            <div style="margin: 8px 0;">
                                <strong>🏭 Warehouses:</strong><br>
                                <small style="color: #666;">${{exchange.warehouses.join(' • ')}}</small>
                            </div>
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px;">
                                <div style="text-align: center; background: #f8f9fa; padding: 8px; border-radius: 8px;">
                                    <strong style="color: #2ecc71;">📦 ${{exchange.capacity}}</strong><br>
                                    <small>Max Capacity</small>
                                </div>
                                <div style="text-align: center; background: #f8f9fa; padding: 8px; border-radius: 8px;">
                                    <strong style="color: #e74c3c;">₦${{exchange.fee}}</strong><br>
                                    <small>Exchange Fee</small>
                                </div>
                            </div>
                            <div style="text-align: center; background: #fff3cd; padding: 8px; border-radius: 8px; margin-top: 10px;">
                                <strong>⏱️ ${{exchange.processing_time}} minutes</strong><br>
                                <small>Processing Time</small>
                            </div>
                        </div>
                    </div>
                `);

            collaborationGroup.addLayer(exchangeMarker);
        }});

        // Create route layers
        routesData.forEach((route, index) => {{
            const group = L.layerGroup();
            const color = route.color;

            // Create route line
            const routeCoords = route.points.map(point => [point.lat, point.lon]);
            const routeLine = L.polyline(routeCoords, {{
                color: color,
                weight: 4,
                opacity: 0.8,
                dashArray: '10, 5'
            }}).bindPopup(`
                <div style="min-width: 200px;">
                    <strong>🚛 ${{route.id}}</strong><br>
                    <strong>Company:</strong> ${{route.company_name || 'Unknown'}}<br>
                    <strong>Vehicle:</strong> ${{route.vehicle}}<br>
                    <strong>Deliveries:</strong> ${{route.stats.deliveries}}<br>
                    <strong>Distance:</strong> ${{route.stats.distance.toFixed(1)}}km<br>
                    <strong>Time:</strong> ${{route.stats.time.toFixed(0)}} minutes<br>
                    <strong>Cost:</strong> ₦${{route.stats.cost.toFixed(0)}}<br>
                    <strong>Efficiency:</strong> ${{route.stats.efficiency}}%
                </div>
            `);

            group.addLayer(routeLine);

            // Add delivery markers (skip depot at start and end)
            route.points.slice(1, -1).forEach((point, pointIndex) => {{
                const deliveryIcon = L.divIcon({{
                    className: 'delivery-marker',
                    html: `<div style="background: ${{color}}; color: white; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center; font-weight: bold; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.2); font-size: 12px;">${{pointIndex + 1}}</div>`,
                    iconSize: [25, 25],
                    iconAnchor: [12.5, 12.5]
                }});

                const marker = L.marker([point.lat, point.lon], {{icon: deliveryIcon}})
                    .bindPopup(`
                        <div style="min-width: 180px;">
                            <strong>📦 ${{point.name}}</strong><br>
                            <strong>Destination:</strong> ${{point.destination || 'Unknown'}}<br>
                            <strong>Company:</strong> ${{point.company || route.company_id}}<br>
                            <strong>Route:</strong> ${{route.id}}<br>
                            <strong>Weight:</strong> ${{point.weight}}kg<br>
                            <strong>Size:</strong> ${{point.size}}<br>
                            <strong>Priority:</strong> ${{point.priority}}<br>
                            <strong>Sequence:</strong> #${{pointIndex + 1}}
                        </div>
                    `);

                group.addLayer(marker);
            }});

            routeGroups[route.id] = group;
            group.addTo(map);
        }});

        // Enhanced control functions
        function toggleRoute(routeId) {{
            const group = routeGroups[routeId];
            if (map.hasLayer(group)) {{
                map.removeLayer(group);
            }} else {{
                map.addLayer(group);
            }}
        }}

        function showAllRoutes() {{
            Object.values(routeGroups).forEach(group => {{
                if (!map.hasLayer(group)) {{
                    map.addLayer(group);
                }}
            }});
        }}

        function hideAllRoutes() {{
            Object.values(routeGroups).forEach(group => {{
                if (map.hasLayer(group)) {{
                    map.removeLayer(group);
                }}
            }});
        }}

        function toggleWarehouses() {{
            if (warehousesVisible) {{
                map.removeLayer(warehouseGroup);
                warehousesVisible = false;
            }} else {{
                map.addLayer(warehouseGroup);
                warehousesVisible = true;
            }}
        }}

        function toggleCollaboration() {{
            if (collaborationVisible) {{
                map.removeLayer(collaborationGroup);
                collaborationVisible = false;
            }} else {{
                map.addLayer(collaborationGroup);
                collaborationVisible = true;
            }}
        }}

        function fitMapToAll() {{
            const allPoints = [];

            // Add route points
            routesData.forEach(route => {{
                route.points.forEach(point => {{
                    allPoints.push([point.lat, point.lon]);
                }});
            }});

            // Add warehouse points
            warehousesData.forEach(warehouse => {{
                allPoints.push([warehouse.lat, warehouse.lon]);
            }});

            // Add collaboration points
            collaborationData.forEach(exchange => {{
                allPoints.push([exchange.lat, exchange.lon]);
            }});

            if (allPoints.length > 0) {{
                const group = new L.featureGroup(allPoints.map(point => L.marker(point)));
                map.fitBounds(group.getBounds().pad(0.1));
            }}
        }}

        function showCompanyFilter() {{
            document.getElementById('companyFilter').style.display = 'block';
        }}

        function hideCompanyFilter() {{
            document.getElementById('companyFilter').style.display = 'none';
        }}

        function applyCompanyFilter() {{
            const checkboxes = document.querySelectorAll('#companyFilter input[type="checkbox"]');
            const selectedCompanies = Array.from(checkboxes)
                .filter(cb => cb.checked)
                .map(cb => cb.value);

            // Hide all routes first
            Object.values(routeGroups).forEach(group => {{
                map.removeLayer(group);
            }});

            // Show only selected company routes
            routesData.forEach(route => {{
                if (selectedCompanies.includes(route.company_id)) {{
                    const group = routeGroups[route.id];
                    if (group) {{
                        map.addLayer(group);
                    }}
                }}
            }});

            hideCompanyFilter();
        }}

        // ===== ANIMATED ROUTE VISUALIZATION =====

        function createMovingVehicle(route, color) {{
            const vehicleIcon = L.divIcon({{
                className: 'moving-vehicle',
                html: `
                    <div style="
                        background: ${{color}};
                        color: white;
                        border-radius: 50%;
                        width: 30px;
                        height: 30px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-weight: bold;
                        border: 3px solid white;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                        font-size: 14px;
                        animation: pulse 2s infinite;
                    ">
                        🚚
                    </div>
                `,
                iconSize: [30, 30],
                iconAnchor: [15, 15]
            }});

            return L.marker([route.points[0].lat, route.points[0].lon], {{icon: vehicleIcon}});
        }}

        function animateVehicleMovement(vehicle, route, onComplete) {{
            let currentPointIndex = 0;
            const points = route.points;
            const totalPoints = points.length;
            const animationSpeed = 2000; // 2 seconds per segment

            function moveToNextPoint() {{
                if (currentPointIndex >= totalPoints - 1) {{
                    if (onComplete) onComplete();
                    return;
                }}

                const currentPoint = points[currentPointIndex];
                const nextPoint = points[currentPointIndex + 1];

                // Animate movement to next point
                const startLat = currentPoint.lat;
                const startLon = currentPoint.lon;
                const endLat = nextPoint.lat;
                const endLon = nextPoint.lon;

                let progress = 0;
                const steps = 50;
                const stepTime = animationSpeed / steps;

                const moveStep = () => {{
                    progress += 1 / steps;
                    if (progress > 1) progress = 1;

                    const lat = startLat + (endLat - startLat) * progress;
                    const lon = startLon + (endLon - startLon) * progress;

                    vehicle.setLatLng([lat, lon]);

                    if (progress < 1) {{
                        setTimeout(moveStep, stepTime);
                    }} else {{
                        currentPointIndex++;

                        // Check if this is an exchange point
                        if (isExchangePoint(nextPoint)) {{
                            showExchangeAnimation(nextPoint, () => {{
                                setTimeout(moveToNextPoint, 1000);
                            }});
                        }} else {{
                            setTimeout(moveToNextPoint, 500);
                        }}
                    }}
                }};

                moveStep();
            }}

            moveToNextPoint();
        }}

        function isExchangePoint(point) {{
            return collaborationData.some(collab =>
                Math.abs(collab.lat - point.lat) < 0.01 &&
                Math.abs(collab.lon - point.lon) < 0.01
            );
        }}

        function showExchangeAnimation(point, onComplete) {{
            const exchangeIcon = L.divIcon({{
                className: 'exchange-animation',
                html: `
                    <div style="
                        background: linear-gradient(45deg, #ff6b6b, #4ecdc4);
                        color: white;
                        border-radius: 50%;
                        width: 50px;
                        height: 50px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-weight: bold;
                        border: 4px solid white;
                        box-shadow: 0 6px 20px rgba(0,0,0,0.4);
                        font-size: 20px;
                        animation: exchangePulse 1s ease-in-out 3;
                    ">
                        🔄
                    </div>
                `,
                iconSize: [50, 50],
                iconAnchor: [25, 25]
            }});

            const exchangeMarker = L.marker([point.lat, point.lon], {{icon: exchangeIcon}});
            exchangeLayer.addLayer(exchangeMarker);

            // Show exchange notification
            const popup = L.popup({{
                closeButton: false,
                autoClose: false,
                className: 'exchange-popup'
            }})
            .setLatLng([point.lat, point.lon])
            .setContent(`
                <div style="text-align: center; padding: 10px;">
                    <strong>🔄 PACKAGE EXCHANGE</strong><br>
                    <span style="color: #666;">Processing handoff...</span>
                </div>
            `)
            .openOn(map);

            setTimeout(() => {{
                exchangeLayer.removeLayer(exchangeMarker);
                map.closePopup(popup);
                if (onComplete) onComplete();
            }}, 3000);
        }}

        function startRouteAnimation(routeId) {{
            const route = routesData.find(r => r.id === routeId);
            if (!route || route.points.length < 2) return;

            // Clear existing animations
            stopAllAnimations();

            // Get route color (prefer server-provided color)
            const colors = {{
                'mainland_movers': '#e74c3c',
                'lagoslink_couriers': '#3498db',
                'ekoswift_logistics': '#2ecc71',
                'island_express': '#f39c12'
            }};
            const color = route.color || colors[route.company_id] || '#9b59b6';

            // Create moving vehicle
            const vehicle = createMovingVehicle(route, color);
            animationLayer.addLayer(vehicle);
            movingMarkers.push(vehicle);

            // Start animation
            animateVehicleMovement(vehicle, route, () => {{
                // Animation complete
                setTimeout(() => {{
                    animationLayer.removeLayer(vehicle);
                    const index = movingMarkers.indexOf(vehicle);
                    if (index > -1) movingMarkers.splice(index, 1);
                }}, 2000);
            }});
        }}

        // Animate a collaboration swap: both riders meet at handoff, exchange, then continue
        function startSwapAnimation(collabRouteId) {{
            const collabRoute = routesData.find(r => r.id === collabRouteId && r.type === 'collaboration');
            if (!collabRoute) return;

            // Ensure visibility of involved routes
            const mainGroup = routeGroups[collabRoute.id];
            if (mainGroup && !map.hasLayer(mainGroup)) map.addLayer(mainGroup);

            const clusterId = collabRouteId.substring(collabRouteId.indexOf('_') + 1);
            const handoffRoutes = routesData.filter(r => r.type === 'handoff' && r.id.endsWith('_' + clusterId));
            handoffRoutes.forEach(r => {{ const g = routeGroups[r.id]; if (g && !map.hasLayer(g)) map.addLayer(g); }});

            stopAllAnimations();

            const handoffPoint = collabRoute.points.find(p => p.type === 'handoff') || collabRoute.points[1];

            // Create vehicles
            const mainVehicle = createMovingVehicle(collabRoute, collabRoute.color || '#ff6b6b');
            animationLayer.addLayer(mainVehicle); movingMarkers.push(mainVehicle);

            const sideVehicles = handoffRoutes.map(route => {{
                const v = createMovingVehicle(route, route.color || '#3498db');
                animationLayer.addLayer(v); movingMarkers.push(v);
                return {{ vehicle: v, route }};
            }});

            let arrived = 0;
            const arrivalsNeeded = 1 + sideVehicles.length;
            const onArrive = () => {{
                arrived += 1;
                if (arrived === arrivalsNeeded) {{
                    showExchangeAnimation(handoffPoint, () => {{
                        // Main rider continues deliveries after exchange
                        animateThroughPoints(mainVehicle, collabRoute.points, 1, 1000, () => {{
                            setTimeout(() => {{
                                animationLayer.removeLayer(mainVehicle);
                                const idx = movingMarkers.indexOf(mainVehicle);
                                if (idx > -1) movingMarkers.splice(idx, 1);
                            }}, 1500);
                        }});
                        // Other riders return to their depots
                        sideVehicles.forEach(({{vehicle, route}}) => {{
                            animateThroughPoints(vehicle, route.points, 1, 1000, () => {{
                                setTimeout(() => {{
                                    animationLayer.removeLayer(vehicle);
                                    const i = movingMarkers.indexOf(vehicle);
                                    if (i > -1) movingMarkers.splice(i, 1);
                                }}, 800);
                            }});
                        }});
                    }});
                }}
            }};

            function animateSegment(vehicle, pStart, pEnd, duration, cb) {{
                const startLat = pStart.lat, startLon = pStart.lon;
                const endLat = pEnd.lat, endLon = pEnd.lon;
                const steps = 60; const stepTime = duration / steps;
                let i = 0;
                const stepFn = () => {{
                    i++;
                    const t = Math.min(1, i/steps);
                    const lat = startLat + (endLat - startLat) * t;
                    const lon = startLon + (endLon - startLon) * t;
                    vehicle.setLatLng([lat, lon]);
                    if (t < 1) setTimeout(stepFn, stepTime);
                    else if (cb) cb();
                }};
                stepFn();
            }}

            function animateThroughPoints(vehicle, points, startIndex, durationPerLeg, done) {{
                let idx = startIndex;
                const nextLeg = () => {{
                    if (idx >= points.length - 1) {{ if (done) done(); return; }}
                    animateSegment(vehicle, points[idx], points[idx+1], durationPerLeg, () => {{
                        idx += 1;
                        setTimeout(nextLeg, 300);
                    }});
                }};
                nextLeg();
            }}

            // Start: move all riders to handoff concurrently
            animateSegment(mainVehicle, collabRoute.points[0], handoffPoint, 2000, onArrive);
            sideVehicles.forEach(({{vehicle, route}}) => {{
                animateSegment(vehicle, route.points[0], handoffPoint, 2000, onArrive);
            }});
        }}

        function stopAllAnimations() {{
            movingMarkers.forEach(marker => {{
                animationLayer.removeLayer(marker);
            }});
            movingMarkers = [];
            exchangeLayer.clearLayers();
        }}

        function animateAllRoutes() {{
            // Clear existing animations
            stopAllAnimations();

            // Start animation for each route with a delay
            routesData.forEach((route, index) => {{
                setTimeout(() => {{
                    startRouteAnimation(route.id);
                }}, index * 1000); // 1 second delay between each route
            }});
        }}

        // Add CSS for animations
        const style = document.createElement('style');
        style.textContent = `
            @keyframes pulse {{
                0% {{ transform: scale(1); }}
                50% {{ transform: scale(1.1); }}
                100% {{ transform: scale(1); }}
            }}

            @keyframes exchangePulse {{
                0% {{ transform: scale(1) rotate(0deg); }}
                50% {{ transform: scale(1.3) rotate(180deg); }}
                100% {{ transform: scale(1) rotate(360deg); }}
            }}

            @keyframes exchangeGlow {{
                0% {{ box-shadow: 0 4px 15px rgba(243, 156, 18, 0.4); }}
                50% {{ box-shadow: 0 6px 25px rgba(243, 156, 18, 0.8); }}
                100% {{ box-shadow: 0 4px 15px rgba(243, 156, 18, 0.4); }}
            }}

            .moving-vehicle {{
                z-index: 1000 !important;
            }}

            .exchange-animation {{
                z-index: 1001 !important;
            }}

            .exchange-popup .leaflet-popup-content-wrapper {{
                background: linear-gradient(45deg, #ff6b6b, #4ecdc4);
                color: white;
                border-radius: 10px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            }}

            .route-controls {{
                margin-top: 10px;
                text-align: center;
            }}

            .animate-btn {{
                background: linear-gradient(45deg, #667eea, #764ba2);
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 20px;
                cursor: pointer;
                margin: 0 5px;
                font-size: 12px;
                transition: all 0.3s ease;
            }}

            .animate-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            }}

            .animate-btn:active {{
                transform: translateY(0);
            }}
            .filter-panel {{
                position: absolute;
                top: 60px;
                right: 20px;
                background: white;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 5px 20px rgba(0,0,0,0.3);
                z-index: 1000;
                min-width: 250px;
            }}
            .company-checkboxes {{
                margin: 15px 0;
            }}
            .company-checkboxes label {{
                display: block;
                margin: 8px 0;
                cursor: pointer;
            }}
            .apply-filter-btn, .close-filter-btn {{
                padding: 8px 15px;
                margin: 5px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
            }}
            .apply-filter-btn {{
                background: #2ecc71;
                color: white;
            }}
            .close-filter-btn {{
                background: #e74c3c;
                color: white;
            }}

            /* Mobile Responsive Design */
            @media (max-width: 768px) {{
                .container {{
                    padding: 10px;
                }}

                .form-row {{
                    grid-template-columns: 1fr;
                    gap: 10px;
                }}

                .form-section {{
                    padding: 15px;
                }}

                .header h1 {{
                    font-size: 1.8rem;
                }}

                .subtitle {{
                    font-size: 0.9rem;
                }}

                .btn {{
                    padding: 12px 20px;
                    font-size: 0.9rem;
                }}

                .stats-grid {{
                    grid-template-columns: 1fr 1fr;
                    gap: 10px;
                }}

                .control-btn {{
                    padding: 8px 12px;
                    font-size: 0.8rem;
                }}

                .filter-panel {{
                    right: 10px;
                    left: 10px;
                    width: auto;
                    min-width: auto;
                }}

                #map {{
                    height: 400px;
                }}
            }}

            @media (max-width: 480px) {{
                .form-section h4 {{
                    font-size: 1rem;
                }}

                .form-group label {{
                    font-size: 0.9rem;
                }}

                .form-group input,
                .form-group select,
                .form-group textarea {{
                    font-size: 0.9rem;
                    padding: 8px;
                }}

                .stats-grid {{
                    grid-template-columns: 1fr;
                }}

                .map-controls {{
                    flex-wrap: wrap;
                    gap: 5px;
                }}

                .control-btn {{
                    flex: 1;
                    min-width: 80px;
                }}
            }}
        `;
        document.head.appendChild(style);

        // Toggle between collaboration and individual views
        function toggleViewMode() {{
            const currentType = '{route_type}';
            const newType = currentType === 'collaboration' ? 'individual' : 'collaboration';
            window.location.href = `/map?type=${{newType}}`;
        }}

        // Initial fit to show all elements
        setTimeout(fitMapToAll, 1000);
    </script>
</body>
</html>
        """

        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html_content.encode())

    def serve_results_page(self):
        """Serve the optimization results page"""
        if not self.optimizer.optimized_routes:
            # Redirect to main page if no results
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()
            return

        results = self.optimizer.optimization_results
        routes = self.optimizer.optimized_routes

        # Generate route cards HTML
        route_cards = ""
        for route in routes:
            deliveries_html = ""
            for delivery in route['deliveries']:
                deliveries_html += f"""
                    <div class="delivery-step">
                        <div class="step-number">{delivery['sequence']}</div>
                        <div class="step-details">
                            <div class="step-id">{delivery['delivery_id']}</div>
                            <div class="step-info">
                                📏 {delivery['distance_from_previous']:.1f}km |
                                ⏱️ {delivery['estimated_time']:.1f}min |
                                📦 {delivery['package_weight']}kg
                            </div>
                        </div>
                    </div>
                """

            route_cards += f"""
                <div class="route-card">
                    <div class="route-header">
                        <div class="route-title">
                            <i class="fas fa-route"></i> {route['route_id']}
                        </div>
                        <div class="route-vehicle">
                            <i class="fas fa-truck"></i> {route['vehicle_type']}
                        </div>
                    </div>

                    <div class="route-stats">
                        <div class="stat">
                            <div class="stat-value">{route['total_deliveries']}</div>
                            <div class="stat-label">Deliveries</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">{route['total_distance_km']}</div>
                            <div class="stat-label">KM</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">{route['total_time_minutes']:.0f}</div>
                            <div class="stat-label">Minutes</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">₦{route['total_cost_naira']:.0f}</div>
                            <div class="stat-label">Cost</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">{route['efficiency_score']:.0f}</div>
                            <div class="stat-label">Efficiency</div>
                        </div>
                    </div>

                    <div class="route-deliveries">
                        <h4><i class="fas fa-list-ol"></i> Delivery Sequence</h4>
                        <div class="delivery-steps">
                            <div class="delivery-step depot">
                                <div class="step-number">🏢</div>
                                <div class="step-details">
                                    <div class="step-id">DEPOT START</div>
                                    <div class="step-info">Lagos Distribution Center</div>
                                </div>
                            </div>
                            {deliveries_html}
                            <div class="delivery-step depot">
                                <div class="step-number">🏢</div>
                                <div class="step-details">
                                    <div class="step-id">DEPOT RETURN</div>
                                    <div class="step-info">Return to Distribution Center</div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            """

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Last-Mile - Optimization Results</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }}

        .main-container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header {{
            text-align: center;
            margin-bottom: 40px;
            color: white;
        }}

        .header h1 {{
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 10px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }}

        .summary-card {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }}

        .summary-stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .summary-stat {{
            text-align: center;
            padding: 20px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border-radius: 12px;
        }}

        .summary-stat .value {{
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 5px;
        }}

        .summary-stat .label {{
            font-size: 0.9rem;
            opacity: 0.9;
        }}

        .routes-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 30px;
        }}

        .route-card {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            border: 1px solid rgba(255,255,255,0.2);
        }}

        .route-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #f1f2f6;
        }}

        .route-title {{
            font-size: 1.3rem;
            font-weight: 600;
            color: #667eea;
        }}

        .route-vehicle {{
            background: linear-gradient(135deg, #27ae60, #2ecc71);
            color: white;
            padding: 8px 15px;
            border-radius: 20px;
            font-size: 0.9rem;
            font-weight: 500;
        }}

        .route-stats {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 15px;
            margin-bottom: 25px;
        }}

        .stat {{
            text-align: center;
            padding: 15px 10px;
            background: rgba(102, 126, 234, 0.1);
            border-radius: 10px;
        }}

        .stat-value {{
            font-size: 1.2rem;
            font-weight: 700;
            color: #667eea;
            margin-bottom: 5px;
        }}

        .stat-label {{
            font-size: 0.8rem;
            color: #7f8c8d;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .route-deliveries h4 {{
            color: #2c3e50;
            margin-bottom: 15px;
            font-weight: 600;
        }}

        .delivery-steps {{
            max-height: 300px;
            overflow-y: auto;
        }}

        .delivery-step {{
            display: flex;
            align-items: center;
            padding: 12px;
            margin-bottom: 8px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}

        .delivery-step.depot {{
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.1), rgba(118, 75, 162, 0.1));
            border-left-color: #764ba2;
        }}

        .step-number {{
            width: 40px;
            height: 40px;
            background: #667eea;
            color: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            margin-right: 15px;
            font-size: 0.9rem;
        }}

        .delivery-step.depot .step-number {{
            background: #764ba2;
        }}

        .step-details {{
            flex: 1;
        }}

        .step-id {{
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 3px;
        }}

        .step-info {{
            font-size: 0.85rem;
            color: #7f8c8d;
        }}

        .action-buttons {{
            display: flex;
            gap: 15px;
            justify-content: center;
            margin-top: 30px;
        }}

        .btn {{
            padding: 15px 30px;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s ease;
        }}

        .btn-primary {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }}

        .btn-success {{
            background: linear-gradient(135deg, #27ae60, #2ecc71);
            color: white;
        }}

        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        }}

        @media (max-width: 768px) {{
            .routes-grid {{
                grid-template-columns: 1fr;
            }}
            .route-stats {{
                grid-template-columns: repeat(3, 1fr);
            }}
            .summary-stats {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
    </style>
</head>
<body>
    <div class="main-container">
        <div class="header">
            <h1><i class="fas fa-chart-line"></i> Optimization Results</h1>
            <div class="subtitle">Multi-Delivery Route Optimization Complete</div>
        </div>

        <div class="summary-card">
            <h2 style="margin-bottom: 25px; color: #2c3e50;"><i class="fas fa-analytics"></i> Optimization Summary</h2>

            <div class="summary-stats">
                <div class="summary-stat">
                    <div class="value">{results['total_routes']}</div>
                    <div class="label">Optimized Routes</div>
                </div>
                <div class="summary-stat">
                    <div class="value">{results['total_deliveries']}</div>
                    <div class="label">Total Deliveries</div>
                </div>
                <div class="summary-stat">
                    <div class="value">{results['total_distance_km']}</div>
                    <div class="label">Total Distance (KM)</div>
                </div>
                <div class="summary-stat">
                    <div class="value">{results['total_time_minutes']:.0f}</div>
                    <div class="label">Total Time (Min)</div>
                </div>
                <div class="summary-stat">
                    <div class="value">₦{results['total_cost_naira']:.0f}</div>
                    <div class="label">Total Cost</div>
                </div>
                <div class="summary-stat">
                    <div class="value">{results['average_deliveries_per_route']:.1f}</div>
                    <div class="label">Avg Deliveries/Route</div>
                </div>
            </div>
        </div>

        <div class="routes-grid">
            {route_cards}
        </div>

        <div class="action-buttons">
            <a href="/" class="btn btn-primary">
                <i class="fas fa-plus"></i> Add More Deliveries
            </a>
            <a href="/map" class="btn btn-success">
                <i class="fas fa-map-marked-alt"></i> View Map
            </a>
            <button onclick="window.print() - multi_delivery_app.py:3244" class="btn btn-secondary">
                <i class="fas fa-print"></i> Print Results
            </button>
        </div>
    </div>
</body>
</html>
        """

        return html_content

def run_server(port=8001):
    """Run the multi-delivery optimization server"""
    server_address = ('', port)
    httpd = HTTPServer(server_address, MultiDeliveryHandler)
    print(f"Starting LastMMile MultiDelivery Optimizer on port {port} - multi_delivery_app.py:3259")
    print(f"Open your browser and go to: http://localhost:{port} - multi_delivery_app.py:3260")
    print("Press Ctrl+C to stop the server - multi_delivery_app.py:3261")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped! - multi_delivery_app.py:3266")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
