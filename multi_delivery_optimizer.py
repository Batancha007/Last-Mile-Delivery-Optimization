# -*- coding: utf-8 -*-
"""
MultiDeliveryOptimizer: uses trained models from models/ to estimate travel time
and build optimized delivery routes for multi_delivery_app.py
Enhanced with clustering, collaboration detection, and hand-off optimization
"""
import os
import json
import math
import pickle
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn  # ensure available for unpickling
from sklearn.cluster import DBSCAN, KMeans
from scipy.spatial.distance import cdist
from shapely.geometry import LineString, Point, Polygon, MultiPoint

# Optional forecasting and RL planners (graceful degradation if unavailable)
try:
    from temporal_forecasting import LSTMForecaster
except Exception:  # pragma: no cover
    LSTMForecaster = None  # type: ignore

try:
    from rl_optimizer import RLRouteOptimizer
except Exception:  # pragma: no cover
    RLRouteOptimizer = None  # type: ignore

MODELS_DIR = "models"

# Resolve models directory robustly (env override, then beside this file)
def _resolve_models_dir() -> Path:
    env = os.environ.get("MODELS_DIR")
    if env:
        p = Path(env)
        if p.exists() and p.is_dir():
            return p
    here = Path(__file__).parent
    candidates = [
        here / "models",
        Path.cwd() / "models",
        here.parent / "models",
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c
    # Default to here/models so error indicates expected location
    return candidates[0]


# Map web app company keys to dataset company names for encoder compatibility
COMPANY_KEY_TO_DSNAME = {
    "mainland_movers": "Mainland Movers",
    "lagoslink_couriers": "LagosLink Couriers",
    "ekoswift_logistics": "EkoSwift Logistics",
    "island_express": "Island Express",
}
def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1 = np.radians(a)
    lat2, lon2 = np.radians(b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    r = 6371.0088
    h = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    return 2*r*np.arcsin(np.sqrt(h))

def linestring_from_route(route: List[Tuple[float, float]]) -> LineString:
    return LineString([(lon, lat) for (lat, lon) in route])

def cluster_polygon(df_cluster: pd.DataFrame) -> Polygon:
    pts = [(lon, lat) for lat, lon in zip(df_cluster["lat"], df_cluster["lon"])]
    if len(pts) >= 3:
        return LineString(pts).buffer(0.01).envelope.buffer(0.005)  # a small "zone"
    elif len(pts) == 2:
        return LineString(pts).buffer(0.01)
    elif len(pts) == 1:
        return Point(pts[0]).buffer(0.01)
    return Point(0, 0).buffer(0.01)

def polygon_from_points_latlon(points: List[Tuple[float, float]]) -> Optional[Polygon]:
    """Build a simple polygon envelope from (lat, lon) points using convex hull.
    Falls back to a small buffer if too few points.
    """
    pts = [(lon, lat) for (lat, lon) in points if lat is not None and lon is not None]
    if not pts:
        return None
    if len(pts) == 1:
        return Point(pts[0]).buffer(0.005)
    try:
        hull = MultiPoint(pts).convex_hull
        if hull.area == 0:
            hull = hull.buffer(0.005)
        return hull.buffer(0.002)
    except Exception:
        try:
            return LineString(pts).buffer(0.005)
        except Exception:
            return Point(pts[0]).buffer(0.005)

def choose_handoff_point(route_a: List[Tuple[float, float]],
                         route_b: List[Tuple[float, float]],
                         fallback_polygon: Polygon) -> Tuple[float, float]:
    la = linestring_from_route(route_a)
    lb = linestring_from_route(route_b)
    inter = la.intersection(lb)
    if not inter.is_empty:
        pt = inter if isinstance(inter, Point) else inter.representative_point()
        return (pt.y, pt.x)
    c = fallback_polygon.centroid
    return (c.y, c.x)

def transform_safe(encoder, values: List[str]) -> np.ndarray:
    classes = list(getattr(encoder, "classes_", []))
    fallback = None
    if "unknown" in classes:
        fallback = "unknown"
    elif classes:
        fallback = classes[0]
    out: List[int] = []
    for v in values:
        try:
            out.append(int(encoder.transform([str(v)])[0]))
        except Exception:
            if fallback is not None:
                out.append(int(encoder.transform([fallback])[0]))
            else:
                out.append(0)
    return np.array(out, dtype=float)

class MultiDeliveryOptimizer:
    """
    Loads trained artifacts and provides delivery storage and route optimization.
    The learned model predicts actual_time_min given engineered features.
    """
    def __init__(self):
        # Data stores
        self.deliveries: List[Dict] = []
        self.original_deliveries: List[Dict] = []  # Store original deliveries for individual routes
        self.optimized_routes: List[Dict] = []
        self.optimization_results: Dict = {}

        # Clustering and collaboration data
        self.delivery_clusters: List[Dict] = []
        self.collaboration_opportunities: List[Dict] = []
        self.collaboration_routes: List[Dict] = []
        self.individual_routes: List[Dict] = []
        self.collaboration_handoffs: List[Dict] = []

        # TSP optimization tracking
        self.optimization_steps: List[Dict] = []
        # Optional multiple plan variants storage
        self.route_plan_variants: List[List[Dict]] = []

    @staticmethod
    def _deg_to_km(deg: float) -> float:
        """Approximate degrees to kilometers conversion (lat/lon)."""
        return float(deg) * 111.0

        # Load artifacts
        self.best_model = None
        self.scaler = None
        self.encoders: Dict[str, object] = {}
        self.feature_list: List[str] = []
        self.metadata: Dict = {}
        self._load_artifacts()

        # Optional LSTM forecaster and RL planner
        self.forecaster = None
        self.rl_planner = None
        try:
            models_dir = _resolve_models_dir()
            if LSTMForecaster is not None:
                lstm_path = str((models_dir / "lstm_forecaster.pt").resolve())
                self.forecaster = LSTMForecaster.load_from(lstm_path)
        except Exception:
            self.forecaster = None
        try:
            models_dir = _resolve_models_dir()
            if RLRouteOptimizer is not None:
                rl_path = str((models_dir / "rl_policy.pt").resolve())
                self.rl_planner = RLRouteOptimizer.load_from(rl_path)
        except Exception:
            self.rl_planner = None

        # Company network and optional static exchange points
        self.companies: Dict[str, Dict] = self._default_companies()
        self.exchange_points: List[Dict] = self._default_exchange_points()

        # Company network with warehouses (for map and depot selection)
        self.companies: Dict[str, Dict] = self._default_companies()
        self.exchange_points: List[Dict] = self._default_exchange_points()

        # Configuration
        self.base_cost_per_km = 200.0  # naira/km
        self.base_stop_fee = 150.0     # naira per stop
        self.default_weather = "sunny"
        self.default_traffic = "moderate"
        
        # Clustering parameters
        self.cluster_radius_km = 5.0  # DBSCAN radius for clustering
        self.min_cluster_size = 2     # Minimum deliveries per cluster
        self.collaboration_threshold_km = 10.0  # Max distance for collaboration
        # Prefer using an existing delivery stop as handoff if it lies near
        # the inter-company path (km distance to line <= threshold)
        self.handoff_existing_stop_threshold_km = 0.75
        # Privacy configuration defaults for DP aggregation
        self.dp_defaults = {"epsilon": 1.0, "delta": 1e-5, "clip_C": 1.0}

    def clear_deliveries(self) -> None:
        """Completely clear all delivery data and all derived/cached structures.

        This resets the optimizer to a pre-delivery state so that UI actions
        like "Clear All" truly remove any existing orders and any computed
        routes/results that depend on them.
        """
        # Core inputs
        self.deliveries = []
        self.original_deliveries = []

        # Derived structures and caches
        self.delivery_clusters = []
        self.collaboration_opportunities = []
        self.individual_routes = []
        self.collaboration_routes = []
        self.collaboration_handoffs = []
        self.optimized_routes = []
        self.optimization_results = {}
        self.optimization_steps = []

    def _load_artifacts(self):
        models_dir = _resolve_models_dir()
        meta_path = (models_dir / "metadata.json")
        model_path = (models_dir / "best_model.pkl")
        scaler_path = (models_dir / "feature_scaler.pkl")
        encoders_path = (models_dir / "encoders.pkl")
        # Make artifacts optional to allow LSTM/RL-only setups
        if meta_path.exists():
            try:
                with open(meta_path, "r") as f:
                    self.metadata = json.load(f)
                    self.feature_list = list(self.metadata.get("features", []))
            except Exception:
                self.metadata = {}
                self.feature_list = []
        if model_path.exists():
            try:
                with open(model_path, "rb") as f:
                    self.best_model = pickle.load(f)
            except Exception:
                self.best_model = None
        if scaler_path.exists():
            try:
                with open(scaler_path, "rb") as f:
                    self.scaler = pickle.load(f)
            except Exception:
                self.scaler = None
        if encoders_path.exists():
            try:
                with open(encoders_path, "rb") as f:
                    self.encoders = pickle.load(f)
            except Exception:
                self.encoders = {}

    # ------------------------
    # Geospatial Overlap Logic
    # ------------------------
    def _company_delivery_polygon(self, company: str) -> Optional[Polygon]:
        """Create a firm-specific delivery polygon from current deliveries."""
        pts = [(float(d.get("lat")), float(d.get("lon"))) for d in self.deliveries if d.get("company") == company]
        if not pts:
            return None
        return polygon_from_points_latlon(pts)

    def _deliveries_in_polygon(self, company: str, poly: Polygon) -> List[Dict]:
        out: List[Dict] = []
        for d in self.deliveries:
            if d.get("company") != company:
                continue
            try:
                p = Point(float(d["lon"]), float(d["lat"]))
                if poly.contains(p) or poly.intersects(p):
                    out.append(d)
            except Exception:
                continue
        return out

    def detect_geospatial_overlaps(self, min_ratio: float = 0.10) -> List[Dict]:
        """Detect collaboration opportunities via polygon overlaps.

        For each pair of firms, build delivery polygons and compute overlap ratio
        = area(intersection) / area(union). If ratio >= min_ratio, create an
        opportunity with deliveries restricted to the overlap polygon.
        """
        companies = sorted(set(str(d.get("company", "unknown")) for d in self.deliveries))
        polys: Dict[str, Optional[Polygon]] = {c: self._company_delivery_polygon(c) for c in companies}
        opportunities: List[Dict] = []
        for i in range(len(companies)):
            for j in range(i + 1, len(companies)):
                ca, cb = companies[i], companies[j]
                pa, pb = polys.get(ca), polys.get(cb)
                if pa is None or pb is None:
                    continue
                try:
                    inter = pa.intersection(pb)
                    union = pa.union(pb)
                    if union.is_empty or inter.is_empty:
                        continue
                    ratio = 0.0
                    try:
                        ratio = float(inter.area) / float(union.area)
                    except Exception:
                        ratio = 0.0
                    if ratio >= min_ratio:
                        centroid = inter.centroid
                        deliv_a = self._deliveries_in_polygon(ca, inter)
                        deliv_b = self._deliveries_in_polygon(cb, inter)
                        deliveries_by_company = {ca: deliv_a, cb: deliv_b}
                        all_deliveries = deliv_a + deliv_b
                        if len(all_deliveries) < 2:
                            continue
                        center = {"lat": float(centroid.y), "lon": float(centroid.x)}
                        cluster_like = {
                            "cluster_id": f"OVERLAP_{ca[:3].upper()}_{cb[:3].upper()}",
                            "center": center,
                            "deliveries": all_deliveries,
                            "delivery_count": len(all_deliveries),
                            "companies": [ca, cb],
                            "company_count": 2,
                            "radius_km": max(0.5, 1.0),
                        }
                        est_savings = self._estimate_collaboration_savings(cluster_like)
                        score = self._calculate_collaboration_score(cluster_like)
                        opp = {
                            "type": "geospatial_overlap",
                            "cluster_id": cluster_like["cluster_id"],
                            "companies": [ca, cb],
                            "overlap_ratio": ratio,
                            "handoff_point": {"lat": center["lat"], "lon": center["lon"]},
                            "deliveries_by_company": deliveries_by_company,
                            "total_deliveries": len(all_deliveries),
                            "estimated_savings_km": est_savings,
                            "collaboration_score": score,
                        }
                        opportunities.append(opp)
                except Exception:
                    continue
        return opportunities

    # ------------------------
    # Vickrey Auction Helpers
    # ------------------------
    def _network_cost_baseline(self, deliveries_by_company: Dict[str, List[Dict]]) -> float:
        """Approximate baseline network distance: each company serves its own deliveries."""
        dist = 0.0
        for company, deliveries in deliveries_by_company.items():
            if not deliveries:
                continue
            depot = self._company_depot(company)
            pts = [(float(d['lat']), float(d['lon'])) for d in deliveries]
            try:
                order, _ = self._tsp_2opt_order(depot, pts)
                route = [depot] + [pts[i] for i in order] + [depot]
            except Exception:
                route = [depot] + pts + [depot]
            dist += self._route_stats(route)
        return dist

    def _network_cost_if_handle(self, deliveries_by_company: Dict[str, List[Dict]], handling_company: str,
                                handoff_coords: Tuple[float, float]) -> float:
        """Collaborative distance if one company handles all deliveries; others do handoff roundtrips."""
        all_deliveries = []
        for arr in deliveries_by_company.values():
            all_deliveries.extend(arr)
        depot_h = self._company_depot(handling_company)
        pts_all = [(float(d['lat']), float(d['lon'])) for d in all_deliveries]
        try:
            order, _ = self._tsp_2opt_order(handoff_coords, pts_all)
            route_h = [depot_h, handoff_coords] + [pts_all[i] for i in order] + [depot_h]
        except Exception:
            route_h = [depot_h, handoff_coords] + pts_all + [depot_h]
        total = self._route_stats(route_h)
        for company, deliveries in deliveries_by_company.items():
            if company == handling_company and deliveries:
                continue
            depot = self._company_depot(company)
            route = [depot, handoff_coords, depot]
            total += self._route_stats(route)
        return total

    def _vickrey_auction_for_overlap(self, deliveries_by_company: Dict[str, List[Dict]],
                                     handoff_coords: Tuple[float, float]) -> Dict:
        """Second-price auction: winner pays second-highest; bids = baseline - collaborative cost."""
        companies = [c for c, arr in deliveries_by_company.items() if arr]
        if len(companies) < 2:
            return {"winner": companies[0] if companies else None, "price": 0.0, "bids": {}}
        baseline = self._network_cost_baseline(deliveries_by_company)
        bids: Dict[str, float] = {}
        for c in companies:
            collab = self._network_cost_if_handle(deliveries_by_company, c, handoff_coords)
            bids[c] = max(0.0, baseline - collab)
        ranked = sorted(bids.items(), key=lambda kv: kv[1], reverse=True)
        winner, top_bid = ranked[0]
        second_bid = ranked[1][1] if len(ranked) > 1 else 0.0
        price = max(0.0, second_bid)
        return {"winner": winner, "price": price, "bids": bids, "baseline": baseline}

    def _default_companies(self) -> Dict[str, Dict]:
        # Warehouses aligned to Lagos dataset companies
        return {
            "mainland_movers": {
                "name": "Mainland Movers",
                "warehouses": [
                    {"name": "Ikeja Depot", "lat": 6.6018, "lon": 3.3515, "capacity": 1000,
                     "vehicle_fleet": {"bike": 25, "van": 10, "truck": 4},
                     "specialties": ["Same Day", "Express"], "operating_hours": "08:00-18:00"}
                ]
            },
            "lagoslink_couriers": {
                "name": "LagosLink Couriers",
                "warehouses": [
                    {"name": "Victoria Island Hub", "lat": 6.4581, "lon": 3.2916, "capacity": 900,
                     "vehicle_fleet": {"bike": 20, "van": 12, "truck": 3},
                     "specialties": ["Express", "Fragile"], "operating_hours": "08:00-18:00"}
                ]
            },
            "ekoswift_logistics": {
                "name": "EkoSwift Logistics",
                "warehouses": [
                    {"name": "Yaba Logistics Center", "lat": 6.4281, "lon": 3.4219, "capacity": 800,
                     "vehicle_fleet": {"bike": 18, "van": 8, "truck": 2},
                     "specialties": ["Urban Delivery"], "operating_hours": "08:00-18:00"}
                ]
            },
            "island_express": {
                "name": "Island Express",
                "warehouses": [
                    {"name": "Lekki Phase 1 Depot", "lat": 6.6018, "lon": 3.5031, "capacity": 700,
                     "vehicle_fleet": {"bike": 15, "van": 6, "truck": 2},
                     "specialties": ["Island Routes"], "operating_hours": "08:00-18:00"}
                ]
            },
        }

    def _default_exchange_points(self) -> List[Dict]:
        # Disable static swap points; rely on dynamic, fairness-aware handoffs
        return []

    def add_delivery(self, delivery: Dict):
        """
        Accepts delivery dict from client and stores it.
        Required keys: id, company, lat, lon, package_weight, package_size, priority
        """
        required = ["id", "company", "lat", "lon", "package_weight", "package_size", "priority"]
        for k in required:
            if k not in delivery:
                raise ValueError(f"Missing field '{k}' in delivery")
        # Normalize types
        delivery = delivery.copy()
        delivery["lat"] = float(delivery["lat"])
        delivery["lon"] = float(delivery["lon"])
        delivery["package_weight"] = float(delivery.get("package_weight", 0.0))
        delivery["package_size"] = str(delivery.get("package_size", "medium"))
        delivery["company"] = str(delivery.get("company", "unknown"))
        self.deliveries.append(delivery)
        # Store original copy for individual routes
        self.original_deliveries.append(delivery.copy())

    def _vehicle_type_for(self, weight: float, preference: Optional[str]) -> str:
        # Map preference names to model categories
        pref_map = {"Any": None, "Bike": "bike", "Van": "van", "Truck": "truck"}
        p = pref_map.get(preference or "Any")
        if p:
            return p
        if weight <= 10:
            return "bike"
        if weight <= 50:
            return "van"
        return "truck"

    def _normalize_package_size(self, size: str) -> str:
        s = (size or "").strip().lower()
        if "extra" in s:
            return "large"
        if s in ("small", "medium", "large"):
            return s
        # map emoji options like "📦 Medium (2-10kg)" if passed
        if "small" in s:
            return "small"
        if "medium" in s:
            return "medium"
        if "large" in s:
            return "large"
        return "medium"

    def _company_depot(self, company_id: str) -> Tuple[float, float]:
        # Robust: ensure company network is initialized
        if not hasattr(self, 'companies') or not isinstance(getattr(self, 'companies'), dict) or not self.companies:
            try:
                self.companies = self._default_companies()
            except Exception:
                self.companies = {}
        c = self.companies.get(company_id)
        if not c:
            return (6.5244, 3.3792)
        whs = c.get("warehouses", [])
        if not whs:
            return (6.5244, 3.3792)
        w0 = whs[0]
        return (float(w0["lat"]), float(w0["lon"]))

    def _encode_features_df(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # Ensure expected base numeric fields exist
        base_numeric = ["distance_km","package_weight_kg","hour_of_day","pickup_lat","pickup_lon","dropoff_lat","dropoff_lon"]
        for col in base_numeric:
            if col not in df.columns:
                df[col] = 0.0
        # Categorical according to encoders
        for col in self.encoders.keys():
            if col not in df.columns:
                df[col] = ""
        # Apply label encoders into *_encoded
        for col in self.encoders.keys():
            enc = self.encoders[col]
            df[f"{col}_encoded"] = transform_safe(enc, df[col].astype(str).tolist())
        # Guarantee all model features exist
        for col in self.feature_list:
            if col not in df.columns:
                df[col] = 0.0
        X = df[self.feature_list].astype(float).fillna(0.0)
        return X

    def _predict_minutes(self, start: Tuple[float, float], end: Tuple[float, float], delivery: Dict, hour: Optional[int] = None) -> float:
        """Predict ETA minutes for a leg, preferring LSTM if available.
        Falls back to classical model or a distance/speed heuristic.
        """
        dist = haversine_km(start, end)
        hour_of_day = int(hour if hour is not None else datetime.now().hour)
        pkg_w = float(delivery.get("package_weight", 0.0))
        traffic = delivery.get("traffic_level", self.default_traffic)

        # Prefer LSTM forecaster when available
        try:
            if getattr(self, "forecaster", None) is not None:
                return float(self.forecaster.predict_eta(start, end, delivery, hour=hour_of_day))
        except Exception:
            pass

        # Fallback to classical model if artifacts exist
        try:
            if self.best_model is not None and self.scaler is not None and self.encoders is not None:
                company_key = str(delivery.get("company", "mainland_movers"))
                company = COMPANY_KEY_TO_DSNAME.get(company_key, company_key)
                vehicle_pref = delivery.get("vehicle_preference")
                vehicle_type = self._vehicle_type_for(pkg_w, vehicle_pref)
                pkg_size = self._normalize_package_size(delivery.get("package_size", "medium"))
                weather = delivery.get("weather", self.default_weather)

                row = {
                    "distance_km": dist,
                    "package_weight_kg": pkg_w,
                    "hour_of_day": hour_of_day,
                    "pickup_lat": float(start[0]),
                    "pickup_lon": float(start[1]),
                    "dropoff_lat": float(end[0]),
                    "dropoff_lon": float(end[1]),
                    "company": company,
                    "vehicle_type": vehicle_type,
                    "package_size": pkg_size,
                    "weather": weather,
                    "traffic_level": traffic,
                }
                df = pd.DataFrame([row])
                X = self._encode_features_df(df)
                Xs = self.scaler.transform(X)
                y = self.best_model.predict(Xs)
                try:
                    val = float(y[0])
                except Exception:
                    val = float(np.asarray(y).ravel()[0])
                return max(0.0, val)
        except Exception:
            pass

        # Last resort: distance/speed heuristic with simple traffic factor
        base_speed_kmh = 18.0
        traffic_factor = {"light": 1.2, "moderate": 1.0, "heavy": 0.6}.get(str(traffic).lower(), 1.0)
        speed = max(5.0, base_speed_kmh * traffic_factor)
        eta_min = 60.0 * float(dist) / speed
        eta_min *= (1.0 + min(pkg_w, 50.0)/200.0)
        return float(max(0.0, eta_min))

    def _tsp_2opt_order(self, start: Tuple[float, float], points: List[Tuple[float, float]]) -> Tuple[List[int], List[Dict]]:
        """Route ordering wrapper: prefer RL policy, fallback to 2-opt baseline."""
        # Try RL-based planner if available
        try:
            if getattr(self, "rl_planner", None) is not None:
                order, policy_log = self.rl_planner.plan_order(start, points, deliveries=None, forecaster=getattr(self, "forecaster", None), hour=datetime.now().hour)
                return order, policy_log
        except Exception:
            pass
        # Fallback to original 2-opt baseline
        return self._tsp_2opt_order_baseline(start, points)

    def _tsp_2opt_order_baseline(self, start: Tuple[float, float], points: List[Tuple[float, float]]) -> Tuple[List[int], List[Dict]]:
        """
        Solve TSP using 2-opt algorithm.
        Returns (order, swaps_made)
        """
        n = len(points)
        if n <= 1:
            return list(range(n)), []

        # Initial tour using nearest neighbor
        order = self._nearest_neighbor_order(start, points)
        swaps_made = []

        # Convert to full tour: start -> points in order -> start
        tour = [start] + [points[i] for i in order] + [start]

        improved = True
        iteration = 0
        max_iterations = 100  # Prevent infinite loops

        while improved and iteration < max_iterations:
            improved = False
            iteration += 1

            # Try all possible 2-opt swaps
            for i in range(1, n):  # Skip depot at start
                for j in range(i + 1, n + 1):  # Skip depot at end
                    # Check if swapping edges (i-1,i) and (j-1,j) improves
                    # Current edges: tour[i-1] to tour[i], tour[j-1] to tour[j]
                    # After swap: tour[i-1] to tour[j-1], tour[i] to tour[j]

                    # Calculate current distance
                    current_dist = haversine_km(tour[i-1], tour[i]) + haversine_km(tour[j-1], tour[j])

                    # Calculate new distance after swap
                    new_dist = haversine_km(tour[i-1], tour[j-1]) + haversine_km(tour[i], tour[j])

                    if new_dist < current_dist:
                        # Perform the swap: reverse segment from i to j-1
                        tour[i:j] = reversed(tour[i:j])

                        # Record the swap
                        swap_info = {
                            'iteration': iteration,
                            'swap_type': '2-opt',
                            'edges_swapped': [(i-1, i), (j-1, j)],
                            'points_affected': [order[k-1] for k in range(i, j)],  # Point indices affected
                            'distance_improvement': current_dist - new_dist,
                            'new_tour_segment': [(tour[k][0], tour[k][1]) for k in range(i, j)]
                        }
                        swaps_made.append(swap_info)

                        improved = True
                        break  # Start over after improvement

                if improved:
                    break

        # Extract the order from the optimized tour (skip start and end depots)
        final_order = []
        for point in tour[1:-1]:
            # Find the index in original points
            for idx, p in enumerate(points):
                if abs(p[0] - point[0]) < 1e-6 and abs(p[1] - point[1]) < 1e-6:
                    final_order.append(idx)
                    break

        return final_order, swaps_made

    def _nearest_neighbor_order(self, start: Tuple[float, float], points: List[Tuple[float, float]]) -> List[int]:
        n = len(points)
        unvisited = set(range(n))
        order: List[int] = []
        cur = start
        while unvisited:
            best_i = None
            best_d = float("inf")
            for i in list(unvisited):
                d = haversine_km(cur, points[i])
                if d < best_d:
                    best_d = d
                    best_i = i
            order.append(best_i)
            unvisited.remove(best_i)
            cur = points[best_i]
        return order

    def _route_stats(self, coords: List[Tuple[float, float]]) -> float:
        if len(coords) < 2:
            return 0.0
        total = 0.0
        for i in range(len(coords) - 1):
            a = coords[i]
            b = coords[i+1]
            total += haversine_km(a, b)
        return total

    def cluster_deliveries(self, n_clusters: Optional[int] = None) -> List[Dict]:
        """
        Cluster deliveries using KMeans based on geographic proximity.
        Returns list of cluster dictionaries with delivery assignments.
        """
        if len(self.deliveries) < 2:
            return []

        # Determine number of clusters like in FLOWCHART2.py
        if n_clusters is None:
            n_clusters = max(1, min(6, len(self.deliveries)//6 or 1))

        # Extract coordinates
        coords = np.array([[float(d['lat']), float(d['lon'])] for d in self.deliveries])

        # Apply KMeans clustering
        km = KMeans(n_clusters=n_clusters, n_init="auto", random_state=42)
        cluster_labels = km.fit_predict(coords)

        # Group deliveries by cluster
        clusters = {}
        for i, label in enumerate(cluster_labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(i)

        # Create cluster dictionaries
        cluster_list = []
        for cluster_id, delivery_indices in clusters.items():
            cluster_deliveries = [self.deliveries[i] for i in delivery_indices]

            # Calculate cluster center
            cluster_coords = [coords[i] for i in delivery_indices]
            center_lat = np.mean([c[0] for c in cluster_coords])
            center_lon = np.mean([c[1] for c in cluster_coords])

            # Get companies in this cluster
            companies = list(set(d.get('company', 'unknown') for d in cluster_deliveries))

            cluster_dict = {
                'cluster_id': f'CLUSTER_{cluster_id:02d}',
                'center': {'lat': float(center_lat), 'lon': float(center_lon)},
                'deliveries': cluster_deliveries,
                'delivery_count': len(cluster_deliveries),
                'companies': companies,
                'company_count': len(companies),
                'radius_km': self._calculate_cluster_radius(cluster_coords, (center_lat, center_lon))
            }
            cluster_list.append(cluster_dict)

        self.delivery_clusters = cluster_list
        return cluster_list

    def _calculate_cluster_radius(self, coords: List[Tuple[float, float]], center: Tuple[float, float]) -> float:
        """Calculate the maximum distance from center to any point in cluster"""
        if not coords:
            return 0.0
        distances = [haversine_km(center, c) for c in coords]
        return max(distances)

    def analyze_collaboration(self) -> Tuple[List[Dict], List[Dict]]:
        """
        Analyze collaboration by reassigning orders within clusters to nearest depots.
        Returns updated deliveries and handoff points.
        Based on FLOWCHART2.py implementation.
        """
        if not self.delivery_clusters:
            self.cluster_deliveries()

        updated_deliveries = self.deliveries.copy()
        handoffs = []

        depot_of = {company: self._company_depot(company) for company in self.companies.keys()}

        for cluster in self.delivery_clusters:
            comps = cluster['companies']
            if len(comps) < 2:
                continue

            # Create DataFrame for cluster polygon
            cluster_df = pd.DataFrame({
                'order_id': [d['id'] for d in cluster['deliveries']],
                'company': [d.get('company', 'unknown') for d in cluster['deliveries']],
                'lat': [d['lat'] for d in cluster['deliveries']],
                'lon': [d['lon'] for d in cluster['deliveries']]
            })

            # Reassign orders to nearest depot
            for idx, row in cluster_df.iterrows():
                latlon = (row["lat"], row["lon"])
                best = min(comps, key=lambda c: haversine_km(latlon, depot_of[c]))
                if best != row["company"]:
                    # Update the delivery
                    delivery_idx = next(i for i, d in enumerate(updated_deliveries) if d['id'] == row['order_id'])
                    updated_deliveries[delivery_idx] = updated_deliveries[delivery_idx].copy()
                    updated_deliveries[delivery_idx]['company'] = best

            # Calculate handoff points for pairs that transferred
            poly = cluster_polygon(cluster_df)
            transfers = {}

            for delivery in cluster['deliveries']:
                original_company = delivery.get('company', 'unknown')
                updated_delivery = next(d for d in updated_deliveries if d['id'] == delivery['id'])
                new_company = updated_delivery.get('company', 'unknown')
                if new_company != original_company:
                    key = (original_company, new_company, cluster['cluster_id'])
                    if key not in transfers:
                        transfers[key] = []
                    transfers[key].append(delivery['id'])

            # Create handoff points
            for (frm, to, cid), ids in transfers.items():
                if ids:
                    # Get routes for handoff calculation - create simple routes for companies involved
                    frm_deliveries = [d for d in updated_deliveries if d.get('company') == frm]
                    to_deliveries = [d for d in updated_deliveries if d.get('company') == to]

                    if frm_deliveries and to_deliveries:
                        frm_depot = self._company_depot(frm)
                        to_depot = self._company_depot(to)

                        # Create simple route coordinates
                        frm_coords = [frm_depot] + [(d['lat'], d['lon']) for d in frm_deliveries] + [frm_depot]
                        to_coords = [to_depot] + [(d['lat'], d['lon']) for d in to_deliveries] + [to_depot]

                        hand_pt = choose_handoff_point(frm_coords, to_coords, poly)
                        handoffs.append({
                            'from_company': frm,
                            'to_company': to,
                            'cluster_id': cid,
                            'location': hand_pt,
                            'orders_transferred': ids
                        })

        return updated_deliveries, handoffs

    def detect_collaboration_opportunities(self) -> List[Dict]:
        """
        Detect opportunities for collaboration between companies.
        Looks for shared clusters and route intersections.
        """
        if not self.delivery_clusters:
            self.cluster_deliveries()
        
        opportunities = []

        # 0) Geospatial overlaps based on firm delivery polygons (threshold: 10%)
        try:
            opportunities.extend(self.detect_geospatial_overlaps(min_ratio=0.10))
        except Exception:
            pass
        
        # 1. Shared clusters (multiple companies in same cluster)
        for cluster in self.delivery_clusters:
            if cluster['company_count'] > 1:
                # Calculate potential savings
                companies = cluster['companies']
                deliveries_by_company = {}
                for delivery in cluster['deliveries']:
                    company = delivery.get('company', 'unknown')
                    if company not in deliveries_by_company:
                        deliveries_by_company[company] = []
                    deliveries_by_company[company].append(delivery)
                
                # Find best hand-off point (cluster center or existing exchange point)
                handoff_point = self._find_optimal_handoff_point(cluster)
                
                opportunity = {
                    'type': 'shared_cluster',
                    'cluster_id': cluster['cluster_id'],
                    'companies': companies,
                    'deliveries_by_company': deliveries_by_company,
                    'total_deliveries': cluster['delivery_count'],
                    'handoff_point': handoff_point,
                    'estimated_savings_km': self._estimate_collaboration_savings(cluster),
                    'collaboration_score': self._calculate_collaboration_score(cluster)
                }
                opportunities.append(opportunity)
        
        # 2. Route intersections between different companies
        individual_routes = self._create_individual_routes_for_analysis()
        for i, route1 in enumerate(individual_routes):
            for j, route2 in enumerate(individual_routes[i+1:], i+1):
                if route1['company_id'] != route2['company_id']:
                    intersection = self._find_route_intersection(route1, route2)
                    if intersection:
                        handoff_point = { 'lat': intersection['lat'], 'lon': intersection['lon'], 'name': f"Intersection {route1['route_id']} - {route2['route_id']}" }
                        deliveries_by_company = {
                            route1['company_id']: list(route1.get('deliveries', [])),
                            route2['company_id']: list(route2.get('deliveries', [])),
                        }
                        opportunity = {
                            'type': 'route_intersection',
                            'route1_id': route1['route_id'],
                            'route2_id': route2['route_id'],
                            'companies': [route1['company_id'], route2['company_id']],
                            'intersection_point': intersection,
                            'handoff_point': handoff_point,
                            'deliveries_by_company': deliveries_by_company,
                            'cluster_id': f"INTER_{route1['company_id']}_{route2['company_id']}_{i:02d}_{j:02d}",
                            'estimated_savings_km': intersection.get('savings_km', 0),
                            'collaboration_score': intersection.get('score', 0)
                        }
                        opportunities.append(opportunity)
        
        self.collaboration_opportunities = opportunities
        return opportunities

    def _find_optimal_handoff_point(self, cluster: Dict) -> Dict:
        """Find a dynamic hand-off point for a cluster.
        Preference order:
          1) Intersection of participating companies' routes near the cluster
          2) Nearby existing exchange point
          3) Cluster center as last resort
        Chooses the candidate that minimizes total approach distance from all company depots.
        """
        cluster_center = cluster['center']

        # Build a polygon envelope around the cluster to constrain ad-hoc points
        try:
            import pandas as _pd
            _df = _pd.DataFrame({
                'lat': [d['lat'] for d in cluster['deliveries']],
                'lon': [d['lon'] for d in cluster['deliveries']],
            })
            poly = cluster_polygon(_df)
        except Exception:
            # Fallback small circle around center
            poly = Point(cluster_center['lon'], cluster_center['lat']).buffer(0.01)

        # Pre-compute depots for participating companies
        companies = list(cluster.get('companies', []))
        depots = {c: self._company_depot(c) for c in companies}

        # 1) Route-intersection based candidates (dynamic)
        route_coords_by_company: Dict[str, List[Tuple[float, float]]] = {}
        for c in companies:
            comp_deliveries = [d for d in cluster['deliveries'] if d.get('company') == c]
            if not comp_deliveries:
                continue
            depot = depots[c]
            pts = [(float(d['lat']), float(d['lon'])) for d in comp_deliveries]
            try:
                order, _ = self._tsp_2opt_order(depot, pts)
                coords = [depot] + [pts[i] for i in order] + [depot]
            except Exception:
                coords = [depot] + pts + [depot]
            route_coords_by_company[c] = coords

        candidates: List[Dict] = []

        comp_keys = list(route_coords_by_company.keys())
        for i in range(len(comp_keys)):
            for j in range(i + 1, len(comp_keys)):
                c1, c2 = comp_keys[i], comp_keys[j]
                rc1, rc2 = route_coords_by_company[c1], route_coords_by_company[c2]
                lat, lon = choose_handoff_point(rc1, rc2, poly)
                # Compute per-company approach metrics (distance and predicted time)
                approach_km_list = []
                approach_min_list = []
                for c in companies:
                    dep = depots[c]
                    dkm = haversine_km(dep, (lat, lon))
                    approach_km_list.append(dkm)
                    try:
                        base_meta = cluster['deliveries'][0] if cluster.get('deliveries') else {'package_weight': 0}
                        mins = float(self._predict_minutes(dep, (lat, lon), base_meta))
                    except Exception:
                        mins = (dkm / 30.0) * 60.0  # fallback at 30km/h
                    approach_min_list.append(mins)
                candidates.append({
                    'type': 'route_intersection',
                    'name': f"Dynamic Handoff {c1[:3].upper()}-{c2[:3].upper()}",
                    'lat': lat,
                    'lon': lon,
                    'distance_from_cluster_km': haversine_km((cluster_center['lat'], cluster_center['lon']), (lat, lon)),
                    'exchange_fee': 80,  # ad-hoc field ops
                    'processing_time': 15,
                    '_approach_sum_km': float(sum(approach_km_list)),
                    '_approach_max_km': float(max(approach_km_list) if approach_km_list else 0.0),
                    '_approach_sum_min': float(sum(approach_min_list)),
                    '_approach_max_min': float(max(approach_min_list) if approach_min_list else 0.0),
                })

        # 2) Prefer existing delivery stops near the path between company depots
        #    (minimizes detours/cost by leveraging an already scheduled stop)
        for i in range(len(companies)):
            for j in range(i + 1, len(companies)):
                c1, c2 = companies[i], companies[j]
                dep1, dep2 = depots[c1], depots[c2]
                # Represent the line in (lon, lat) pairs for shapely
                path_ll = LineString([(dep1[1], dep1[0]), (dep2[1], dep2[0])])
                for d in cluster.get('deliveries', []):
                    try:
                        if d.get('company') not in (c1, c2):
                            continue
                        pt = Point(float(d['lon']), float(d['lat']))
                        dist_km = self._deg_to_km(path_ll.distance(pt))
                    except Exception:
                        continue
                    if dist_km <= float(getattr(self, 'handoff_existing_stop_threshold_km', 0.75)):
                        lat, lon = float(d['lat']), float(d['lon'])
                        approach_km_list = []
                        approach_min_list = []
                        for c in companies:
                            dep = depots[c]
                            dkm = haversine_km(dep, (lat, lon))
                            approach_km_list.append(dkm)
                            try:
                                mins = float(self._predict_minutes(dep, (lat, lon), d))
                            except Exception:
                                mins = (dkm / 30.0) * 60.0
                            approach_min_list.append(mins)
                        candidates.append({
                            'type': 'existing_stop',
                            'name': f"Existing Stop {str(d.get('id',''))}",
                            'lat': lat,
                            'lon': lon,
                            'distance_from_cluster_km': haversine_km((cluster_center['lat'], cluster_center['lon']), (lat, lon)),
                            'exchange_fee': 0,
                            'processing_time': 10,
                            '_approach_sum_km': float(sum(approach_km_list)),
                            '_approach_max_km': float(max(approach_km_list) if approach_km_list else 0.0),
                            '_approach_sum_min': float(sum(approach_min_list)),
                            '_approach_max_min': float(max(approach_min_list) if approach_min_list else 0.0),
                        })

        # 3) Nearby existing exchange points
        for exchange in self.exchange_points:
            ex_lat = exchange['location']['lat']
            ex_lon = exchange['location']['lon']
            dist_cluster = haversine_km((cluster_center['lat'], cluster_center['lon']), (ex_lat, ex_lon))
            if dist_cluster <= max(self.collaboration_threshold_km, 10.0):
                approach_km_list = []
                approach_min_list = []
                for c in companies:
                    dep = depots[c]
                    dkm = haversine_km(dep, (ex_lat, ex_lon))
                    approach_km_list.append(dkm)
                    try:
                        base_meta = cluster['deliveries'][0] if cluster.get('deliveries') else {'package_weight': 0}
                        mins = float(self._predict_minutes(dep, (ex_lat, ex_lon), base_meta))
                    except Exception:
                        mins = (dkm / 30.0) * 60.0
                    approach_min_list.append(mins)
                candidates.append({
                    'type': 'existing_exchange',
                    'name': exchange['name'],
                    'lat': ex_lat,
                    'lon': ex_lon,
                    'distance_from_cluster_km': dist_cluster,
                    'exchange_fee': exchange.get('exchange_fee', 100),
                    'processing_time': exchange.get('processing_time', 30),
                    '_approach_sum_km': float(sum(approach_km_list)),
                    '_approach_max_km': float(max(approach_km_list) if approach_km_list else 0.0),
                    '_approach_sum_min': float(sum(approach_min_list)),
                    '_approach_max_min': float(max(approach_min_list) if approach_min_list else 0.0),
                })

        # 4) Cluster center fallback
        candidates.append({
            'type': 'cluster_center',
            'name': f"Handoff Point {cluster['cluster_id']}",
            'lat': cluster_center['lat'],
            'lon': cluster_center['lon'],
            'distance_from_cluster_km': 0.0,
            'exchange_fee': 50,
            'processing_time': 15,
            '_approach_sum_km': float(sum(haversine_km(depots[c], (cluster_center['lat'], cluster_center['lon'])) for c in companies)),
            '_approach_max_km': float(max((haversine_km(depots[c], (cluster_center['lat'], cluster_center['lon'])) for c in companies), default=0.0)),
            '_approach_sum_min': float(sum((
                (float(self._predict_minutes(depots[c], (cluster_center['lat'], cluster_center['lon']), (cluster['deliveries'][0] if cluster.get('deliveries') else {'package_weight':0})))
                    if True else 0.0)  # placeholder to allow try/except below
            ) for c in [])),  # will set below
            '_approach_max_min': 0.0,  # will set below
        })

        # Fill in time metrics for cluster center candidate (index is last element)
        if candidates:
            idx = len(candidates) - 1
            approach_min_list_center = []
            for c in companies:
                dep = depots[c]
                dkm = haversine_km(dep, (cluster_center['lat'], cluster_center['lon']))
                try:
                    base_meta = cluster['deliveries'][0] if cluster.get('deliveries') else {'package_weight': 0}
                    mins = float(self._predict_minutes(dep, (cluster_center['lat'], cluster_center['lon']), base_meta))
                except Exception:
                    mins = (dkm / 30.0) * 60.0
                approach_min_list_center.append(mins)
            candidates[idx]['_approach_sum_min'] = float(sum(approach_min_list_center))
            candidates[idx]['_approach_max_min'] = float(max(approach_min_list_center) if approach_min_list_center else 0.0)

        # Choose best candidate with fairness across time and distance:
        # minimize max approach time, then max distance, then sum time, then sum distance, then exchange fee
        best = min(
            candidates,
            key=lambda x: (
                x.get('_approach_max_min', float('inf')),
                x.get('_approach_max_km', float('inf')),
                x.get('_approach_sum_min', float('inf')),
                x.get('_approach_sum_km', float('inf')),
                x.get('exchange_fee', 0)
            )
        )
        # Drop internal fields
        for k in ('_approach_sum_km','_approach_max_km','_approach_sum_min','_approach_max_min'):
            best.pop(k, None)
        return best

    def _estimate_collaboration_savings(self, cluster: Dict) -> float:
        """Estimate potential distance savings from collaboration"""
        if cluster['company_count'] <= 1:
            return 0.0
        
        # Calculate current total distance (each company goes to all their deliveries)
        current_distance = 0.0
        for company in cluster['companies']:
            company_deliveries = [d for d in cluster['deliveries'] if d.get('company') == company]
            if len(company_deliveries) > 1:
                # Estimate distance for company's deliveries in this cluster
                depot = self._company_depot(company)
                points = [(float(d['lat']), float(d['lon'])) for d in company_deliveries]
                route_coords = [depot] + points + [depot]
                current_distance += self._route_stats(route_coords)
        
        # Calculate collaborative distance (one company handles all, others just go to handoff)
        handoff_point = cluster['center']
        handoff_coords = (handoff_point['lat'], handoff_point['lon'])
        
        # Best company handles all deliveries
        min_collaborative_distance = float('inf')
        for handling_company in cluster['companies']:
            depot = self._company_depot(handling_company)
            all_points = [(float(d['lat']), float(d['lon'])) for d in cluster['deliveries']]
            
            # Route: depot -> handoff -> all deliveries -> depot
            collaborative_route = [depot, handoff_coords] + all_points + [depot]
            collaborative_distance = self._route_stats(collaborative_route)
            
            # Add distances for other companies to reach handoff point
            for other_company in cluster['companies']:
                if other_company != handling_company:
                    other_depot = self._company_depot(other_company)
                    collaborative_distance += 2 * haversine_km(
                        other_depot, handoff_coords
                    )
            
            min_collaborative_distance = min(min_collaborative_distance, collaborative_distance)
        
        return max(0.0, current_distance - min_collaborative_distance)

    def _calculate_collaboration_score(self, cluster: Dict) -> float:
        """Calculate a collaboration score (0-100) based on potential benefits"""
        if cluster['company_count'] <= 1:
            return 0.0
        
        # Factors: number of companies, deliveries, estimated savings, cluster density
        company_factor = min(cluster['company_count'] / 4.0, 1.0) * 30  # Max 30 points
        delivery_factor = min(cluster['delivery_count'] / 10.0, 1.0) * 25  # Max 25 points
        savings_factor = min(self._estimate_collaboration_savings(cluster) / 20.0, 1.0) * 35  # Max 35 points
        density_factor = min(5.0 / cluster['radius_km'], 1.0) * 10  # Max 10 points (smaller radius = higher density)
        
        return company_factor + delivery_factor + savings_factor + density_factor

    def _create_individual_routes_for_analysis(self) -> List[Dict]:
        """Create individual company routes for intersection analysis"""
        if self.individual_routes:
            return self.individual_routes
        
        routes = []
        deliveries_by_company = {}
        for d in self.deliveries:
            company = d.get('company', 'mainland_movers')
            if company not in deliveries_by_company:
                deliveries_by_company[company] = []
            deliveries_by_company[company].append(d)
        
        for company_id, deliveries in deliveries_by_company.items():
            if not deliveries:
                continue

            depot = self._company_depot(company_id)
            points = [(float(d['lat']), float(d['lon'])) for d in deliveries]
            order, swaps = self._tsp_2opt_order(depot, points)

            # Record optimization steps
            if swaps:
                self.optimization_steps.append({
                    'route_id': f"{company_id}_INDIVIDUAL",
                    'company_id': company_id,
                    'algorithm': 'TSP_2opt',
                    'initial_order': 'nearest_neighbor',
                    'swaps_made': swaps,
                    'final_order': order,
                    'deliveries': [d['id'] for d in deliveries]
                })

            route_coords = [depot] + [points[i] for i in order] + [depot]

            route = {
                'route_id': f"{company_id}_INDIVIDUAL",
                'company_id': company_id,
                'coordinates': route_coords,
                'deliveries': [deliveries[i] for i in order],
                'total_distance_km': self._route_stats(route_coords)
            }
            routes.append(route)
        
        self.individual_routes = routes
        return routes

    def _find_route_intersection(self, route1: Dict, route2: Dict) -> Optional[Dict]:
        """Find intersection points between two routes"""
        coords1 = route1['coordinates']
        coords2 = route2['coordinates']
        
        best_intersection = None
        min_total_distance = float('inf')
        
        # Check each segment of route1 against each segment of route2
        for i in range(len(coords1) - 1):
            for j in range(len(coords2) - 1):
                # Find closest approach between segments
                p1_start, p1_end = coords1[i], coords1[i + 1]
                p2_start, p2_end = coords2[j], coords2[j + 1]
                
                # Simple approach: find midpoint of closest segment pair
                distances = [
                    haversine_km(p1_start, p2_start),
                    haversine_km(p1_start, p2_end),
                    haversine_km(p1_end, p2_start),
                    haversine_km(p1_end, p2_end)
                ]
                
                min_dist = min(distances)
                if min_dist <= self.collaboration_threshold_km:
                    # Calculate intersection point (midpoint of closest points)
                    min_idx = distances.index(min_dist)
                    if min_idx == 0:
                        intersection_lat = (p1_start[0] + p2_start[0]) / 2
                        intersection_lon = (p1_start[1] + p2_start[1]) / 2
                    elif min_idx == 1:
                        intersection_lat = (p1_start[0] + p2_end[0]) / 2
                        intersection_lon = (p1_start[1] + p2_end[1]) / 2
                    elif min_idx == 2:
                        intersection_lat = (p1_end[0] + p2_start[0]) / 2
                        intersection_lon = (p1_end[1] + p2_start[1]) / 2
                    else:
                        intersection_lat = (p1_end[0] + p2_end[0]) / 2
                        intersection_lon = (p1_end[1] + p2_end[1]) / 2
                    
                    # Estimate savings (simplified)
                    savings = max(0, (route1['total_distance_km'] + route2['total_distance_km']) * 0.1)
                    
                    if min_dist < min_total_distance:
                        min_total_distance = min_dist
                        best_intersection = {
                            'lat': intersection_lat,
                            'lon': intersection_lon,
                            'distance_between_routes_km': min_dist,
                            'savings_km': savings,
                            'score': max(0, 100 - min_dist * 5)  # Higher score for closer intersections
                        }
        
        return best_intersection

    def build_collaboration_routes(self) -> List[Dict]:
        """
        Build optimized collaboration routes based on detected opportunities.
        """
        if not self.collaboration_opportunities:
            self.detect_collaboration_opportunities()

        collaboration_routes = []
        handoffs_out = []
        processed_deliveries = set()

        # Sort opportunities by collaboration score (highest first)
        sorted_opportunities = sorted(
            self.collaboration_opportunities,
            key=lambda x: x.get('collaboration_score', 0),
            reverse=True
        )

        for opportunity in sorted_opportunities:
            if opportunity['type'] in ('shared_cluster', 'geospatial_overlap', 'route_intersection'):
                routes = self._build_cluster_two_way_collaboration_routes(opportunity, processed_deliveries) or \
                         self._build_cluster_collaboration_route(opportunity, processed_deliveries)
                if routes:
                    collaboration_routes.extend(routes)
                    # Mark deliveries as processed
                    for route in routes:
                        if route.get('type') == 'collaboration':
                            for delivery in route['deliveries']:
                                processed_deliveries.add(delivery['id'])

                    # Record handoff pairs for visualization (each non-handling -> handling)
                    deliveries_by_company = opportunity.get('deliveries_by_company', {})
                    if deliveries_by_company:
                        handling_company = next((r.get('handling_company') for r in routes if r.get('type') == 'collaboration'), None) or \
                                           max(deliveries_by_company.keys(), key=lambda c: len(deliveries_by_company[c]))
                        for company, deliveries in deliveries_by_company.items():
                            if company == handling_company:
                                continue
                            handoffs_out.append({
                                'from_company': company,
                                'to_company': handling_company,
                                'cluster_id': opportunity.get('cluster_id', ''),
                                'location': (opportunity['handoff_point']['lat'], opportunity['handoff_point']['lon']),
                                'orders_transferred': [d['id'] for d in deliveries]
                            })

        # Handle remaining deliveries with individual routes
        remaining_deliveries = [d for d in self.deliveries if d['id'] not in processed_deliveries]
        if remaining_deliveries:
            individual_routes = self._create_routes_for_deliveries(remaining_deliveries)
            collaboration_routes.extend(individual_routes)

        self.collaboration_routes = collaboration_routes
        # Expose handoff points for map visualization
        self.collaboration_handoffs = handoffs_out
        return collaboration_routes

    # ---------- Top-K Collaboration Plans ----------
    def _find_top_handoff_candidates_from_opportunity(self, opportunity: Dict, top_n: int = 2) -> List[Dict]:
        """Return ranked handoff candidates for a given opportunity using simplified
        fairness (sum of approach distance)."""
        deliveries_by_company = opportunity.get('deliveries_by_company', {})
        companies = list(deliveries_by_company.keys())
        all_deliveries: List[Dict] = []
        for arr in deliveries_by_company.values():
            all_deliveries.extend(arr or [])
        if not all_deliveries:
            return [opportunity.get('handoff_point', {})]
        center_lat = float(np.mean([float(d['lat']) for d in all_deliveries]))
        center_lon = float(np.mean([float(d['lon']) for d in all_deliveries]))
        cluster_center = {'lat': center_lat, 'lon': center_lon}

        try:
            import pandas as _pd
            _df = _pd.DataFrame({'lat': [d['lat'] for d in all_deliveries], 'lon': [d['lon'] for d in all_deliveries]})
            poly = cluster_polygon(_df)
        except Exception:
            poly = Point(cluster_center['lon'], cluster_center['lat']).buffer(0.01)

        depots = {c: self._company_depot(c) for c in companies}
        route_coords_by_company: Dict[str, List[Tuple[float, float]]] = {}
        for c in companies:
            comp_deliveries = [d for d in all_deliveries if d.get('company') == c]
            if not comp_deliveries:
                continue
            depot = depots[c]
            pts = [(float(d['lat']), float(d['lon'])) for d in comp_deliveries]
            try:
                order, _ = self._tsp_2opt_order(depot, pts)
                coords = [depot] + [pts[i] for i in order] + [depot]
            except Exception:
                coords = [depot] + pts + [depot]
            route_coords_by_company[c] = coords

        candidates: List[Dict] = []
        comp_keys = list(route_coords_by_company.keys())
        for i in range(len(comp_keys)):
            for j in range(i + 1, len(comp_keys)):
                c1, c2 = comp_keys[i], comp_keys[j]
                rc1, rc2 = route_coords_by_company[c1], route_coords_by_company[c2]
                lat, lon = choose_handoff_point(rc1, rc2, poly)
                total_approach_km = sum(haversine_km(depots[c], (lat, lon)) for c in companies)
                candidates.append({'name': f"Dynamic Handoff {c1[:3].upper()}-{c2[:3].upper()}", 'lat': lat, 'lon': lon, '_score': total_approach_km})

        # Fallback to center
        candidates.append({'name': f"Handoff Point {opportunity.get('cluster_id','OPP')}", 'lat': center_lat, 'lon': center_lon, '_score': sum(haversine_km(depots[c], (center_lat, center_lon)) for c in companies)})

        ranked = sorted(candidates, key=lambda x: x.get('_score', float('inf')))
        out: List[Dict] = []
        for cand in ranked[:max(1, int(top_n))]:
            c = cand.copy()
            c.pop('_score', None)
            out.append(c)
        return out

    def _is_dissimilar_point(self, point: Tuple[float, float], avoid_points: List[Tuple[float, float]],
                              delta_km: float = 1.0) -> bool:
        """Return True if point is at least delta_km away from all avoid_points."""
        if not avoid_points:
            return True
        return all(haversine_km(point, ap) >= max(0.0, float(delta_km)) for ap in avoid_points)

    def _build_collaboration_routes_for_variant(self, variant_index: int = 0,
                                                avoid_points: Optional[List[Tuple[float, float]]] = None,
                                                diversity_radius_km: float = 1.0) -> List[Dict]:
        if not self.collaboration_opportunities:
            self.detect_collaboration_opportunities()
        collaboration_routes: List[Dict] = []
        processed_deliveries: set = set()
        sorted_opportunities = sorted(self.collaboration_opportunities, key=lambda x: x.get('collaboration_score', 0), reverse=True)
        for opportunity in sorted_opportunities:
            if opportunity['type'] in ('shared_cluster', 'geospatial_overlap', 'route_intersection'):
                # Consider more than variant_index+1 to allow diversity filtering
                candidates = self._find_top_handoff_candidates_from_opportunity(opportunity, top_n=max(3, variant_index+2))
                chosen = None
                # Prefer candidates that are dissimilar to baseline handoff points
                if avoid_points:
                    for cand in candidates:
                        pt = (cand.get('lat'), cand.get('lon'))
                        if pt[0] is None or pt[1] is None:
                            continue
                        if self._is_dissimilar_point(pt, avoid_points, delta_km=diversity_radius_km):
                            chosen = cand
                            break
                # Fallback to positional pick if no dissimilar candidate found
                if chosen is None:
                    chosen = candidates[variant_index] if variant_index < len(candidates) else candidates[0]
                opp_mod = dict(opportunity)
                opp_mod['handoff_point'] = {'lat': chosen.get('lat'), 'lon': chosen.get('lon'), 'name': chosen.get('name', 'Handoff')}
                routes = self._build_cluster_two_way_collaboration_routes(opp_mod, processed_deliveries) or self._build_cluster_collaboration_route(opp_mod, processed_deliveries)
                if routes:
                    collaboration_routes.extend(routes)
                    for route in routes:
                        if route.get('type') == 'collaboration':
                            for delivery in route['deliveries']:
                                processed_deliveries.add(delivery['id'])
        remaining_deliveries = [d for d in self.deliveries if d['id'] not in processed_deliveries]
        if remaining_deliveries:
            collaboration_routes.extend(self._create_routes_for_deliveries(remaining_deliveries))
        return collaboration_routes

    def _build_cluster_two_way_collaboration_routes(self, opportunity: Dict, processed_deliveries: set) -> Optional[List[Dict]]:
        """Build two-way collaboration routes when both companies benefit.
        Strategy: assign each delivery in the cluster to the nearest participating company depot.
        Companies then meet at the dynamic handoff point, exchange both ways as needed, and proceed.
        Returns None if no cross-company transfers are found (defer to one-way model).
        """
        cluster_deliveries = opportunity.get('deliveries_by_company', {})
        # Fairness-aware refinement of handoff for this specific opportunity
        handoff_point = opportunity.get('handoff_point')
        try:
            # Build a temporary cluster-like structure
            temp_deliveries: List[Dict] = []
            for arr in cluster_deliveries.values():
                temp_deliveries.extend(arr or [])
            if temp_deliveries:
                center_lat = float(np.mean([float(d['lat']) for d in temp_deliveries]))
                center_lon = float(np.mean([float(d['lon']) for d in temp_deliveries]))
                cluster_like = {
                    'cluster_id': opportunity.get('cluster_id', 'OPP'),
                    'center': {'lat': center_lat, 'lon': center_lon},
                    'deliveries': temp_deliveries,
                    'companies': list(cluster_deliveries.keys()),
                }
                handoff_point = self._find_optimal_handoff_point(cluster_like)
        except Exception:
            pass
        companies = list(cluster_deliveries.keys())
        if len(companies) < 2:
            return None

        # Build list of all deliveries in this cluster and skip those already processed
        all_deliveries = []
        for arr in cluster_deliveries.values():
            for d in arr:
                if d['id'] in processed_deliveries:
                    continue
                all_deliveries.append(d)
        if not all_deliveries:
            return None

        # Pre-compute depots
        depots = {c: self._company_depot(c) for c in companies}

        # Assign each delivery to nearest company depot among participants
        reassigned: Dict[str, List[Dict]] = {c: [] for c in companies}
        gave_to: Dict[str, int] = {c: 0 for c in companies}
        got_from: Dict[str, int] = {c: 0 for c in companies}

        for d in all_deliveries:
            latlon = (float(d['lat']), float(d['lon']))
            best_c = min(companies, key=lambda c: haversine_km(latlon, depots[c]))
            reassigned[best_c].append(d)
            orig = d.get('company')
            if orig != best_c:
                gave_to[orig] = gave_to.get(orig, 0) + 1
                got_from[best_c] = got_from.get(best_c, 0) + 1

        # Check for any cross-company transfers
        total_transfers = sum(gave_to[c] for c in companies)
        if total_transfers == 0:
            return None

        # Build routes for each company according to reassignment
        routes: List[Dict] = []
        handoff_coords = (handoff_point['lat'], handoff_point['lon'])

        for company in companies:
            assigned = reassigned.get(company, [])
            depot = depots[company]
            if assigned:
                # Option A: handoff at start, then all deliveries
                delivery_coords = [(float(d['lat']), float(d['lon'])) for d in assigned]
                order_a, swaps_a = self._tsp_2opt_order(handoff_coords, delivery_coords) if delivery_coords else ([], 0)
                ordered_a = [assigned[i] for i in order_a]
                route_a = [depot, handoff_coords] + [delivery_coords[i] for i in order_a] + [depot]
                dist_a = self._route_stats(route_a)
                time_a = sum(self._predict_minutes(route_a[i], route_a[i+1], ordered_a[0] if ordered_a else assigned[0]) for i in range(len(route_a)-1))

                # Option B: deliver own first, then handoff, then others
                own = [d for d in assigned if str(d.get('company')) == company]
                other = [d for d in assigned if str(d.get('company')) != company]
                if own:
                    own_pts = [(float(d['lat']), float(d['lon'])) for d in own]
                    order_own, _ = self._tsp_2opt_order(depot, own_pts) if own_pts else ([], 0)
                    pre_coords = [depot] + [own_pts[i] for i in order_own] + [handoff_coords]
                    ordered_pre = [own[i] for i in order_own]
                else:
                    pre_coords = [depot, handoff_coords]
                    ordered_pre = []
                if other:
                    other_pts = [(float(d['lat']), float(d['lon'])) for d in other]
                    order_other, _ = self._tsp_2opt_order(handoff_coords, other_pts) if other_pts else ([], 0)
                    post_coords = [handoff_coords] + [other_pts[i] for i in order_other]
                    ordered_post = [other[i] for i in order_other]
                else:
                    post_coords = [handoff_coords]
                    ordered_post = []
                route_b = pre_coords + post_coords[1:] + [depot]
                ordered_b = ordered_pre + ordered_post
                dist_b = self._route_stats(route_b)
                time_b = sum(self._predict_minutes(route_b[i], route_b[i+1], (ordered_b[0] if ordered_b else (ordered_a[0] if ordered_a else assigned[0]))) for i in range(len(route_b)-1))

                # Choose better
                if (dist_b, time_b) < (dist_a, time_a):
                    chosen_coords = route_b
                    chosen_deliveries = ordered_b
                    handoff_stage = 'mid'
                    total_distance = dist_b
                    total_time = time_b
                    swaps = swaps_a  # approximate
                else:
                    chosen_coords = route_a
                    chosen_deliveries = ordered_a
                    handoff_stage = 'start'
                    total_distance = dist_a
                    total_time = time_a
                    swaps = swaps_a

                if swaps:
                    self.optimization_steps.append({
                        'route_id': f"COLLAB_{opportunity['cluster_id']}_{company[:3].upper()}",
                        'company_id': company,
                        'algorithm': 'TSP_2opt',
                        'initial_order': 'nearest_neighbor',
                        'swaps_made': swaps,
                        'final_order': order_a,
                        'deliveries': [d['id'] for d in assigned],
                        'handoff_optimization': True
                    })

                total_cost = float(self.base_stop_fee * len(assigned) + total_distance * self.base_cost_per_km)
                routes.append({
                    'route_id': f"COLLAB_{opportunity['cluster_id']}_{company[:3].upper()}",
                    'type': 'collaboration',
                    'handling_company': company,
                    'participating_companies': companies,
                    'handoff_point': handoff_point,
                    'handoff_stage': handoff_stage,
                    'deliveries': chosen_deliveries,
                    'coordinates': chosen_coords,
                    'total_deliveries': len(assigned),
                    'total_distance_km': round(total_distance, 2),
                    'total_time_minutes': float(total_time),
                    'total_cost_naira': total_cost,
                    'collaboration_savings_km': 0,
                    'collaboration_score': opportunity.get('collaboration_score', 0),
                    'efficiency_score': max(50.0, min(99.0, 100.0 * len(assigned) / (total_distance + 5.0)))
                })
            else:
                if gave_to.get(company, 0) > 0:
                    route_coords = [depot, handoff_coords, depot]
                    handoff_distance = self._route_stats(route_coords)
                    handoff_time = sum(self._predict_minutes(route_coords[i], route_coords[i+1],
                                                            cluster_deliveries[company][0] if cluster_deliveries[company] else {'package_weight': 0})
                                       for i in range(len(route_coords)-1))
                    handoff_cost = float(self.base_stop_fee * 0 + handoff_distance * self.base_cost_per_km)
                    routes.append({
                        'route_id': f"HANDOFF_{company[:3].upper()}_{opportunity['cluster_id']}",
                        'type': 'handoff',
                        'company_id': company,
                        'handoff_point': handoff_point,
                        'deliveries': [],
                        'coordinates': route_coords,
                        'total_deliveries': 0,
                        'total_distance_km': round(handoff_distance, 2),
                        'total_time_minutes': float(handoff_time),
                        'total_cost_naira': handoff_cost,
                        'efficiency_score': 80.0
                    })

        return routes

    def _build_cluster_collaboration_route(self, opportunity: Dict, processed_deliveries: set) -> Optional[List[Dict]]:
        """Build collaboration routes for a shared cluster"""
        cluster_deliveries = opportunity.get('deliveries_by_company', {})
        # Fairness-aware refinement of handoff for this specific opportunity
        handoff_point = opportunity.get('handoff_point')
        try:
            temp_deliveries: List[Dict] = []
            for arr in cluster_deliveries.values():
                temp_deliveries.extend(arr or [])
            if temp_deliveries:
                center_lat = float(np.mean([float(d['lat']) for d in temp_deliveries]))
                center_lon = float(np.mean([float(d['lon']) for d in temp_deliveries]))
                cluster_like = {
                    'cluster_id': opportunity.get('cluster_id', 'OPP'),
                    'center': {'lat': center_lat, 'lon': center_lon},
                    'deliveries': temp_deliveries,
                    'companies': list(cluster_deliveries.keys()),
                }
                handoff_point = self._find_optimal_handoff_point(cluster_like)
        except Exception:
            pass

        # Skip if any deliveries already processed
        all_delivery_ids = set()
        for company_deliveries in cluster_deliveries.values():
            for delivery in company_deliveries:
                if delivery['id'] in processed_deliveries:
                    return None
                all_delivery_ids.add(delivery['id'])

        # Choose handling company via Vickrey auction (second-price). Fallback to max deliveries.
        handoff_coords = (handoff_point['lat'], handoff_point['lon'])
        auction = self._vickrey_auction_for_overlap(cluster_deliveries, handoff_coords)
        handling_company = auction.get('winner') or max(cluster_deliveries.keys(), key=lambda c: len(cluster_deliveries[c]))
        handling_deliveries = cluster_deliveries[handling_company]

        # Build the collaboration route
        depot = self._company_depot(handling_company)
        # handoff_coords defined above

        # Collect all deliveries in cluster (skip already processed)
        all_deliveries = []
        for company_deliveries in cluster_deliveries.values():
            for d in company_deliveries:
                if d['id'] in processed_deliveries:
                    continue
                all_deliveries.append(d)
        if not all_deliveries:
            return None

        # Optimize delivery order with dynamic handoff stage
        delivery_coords = [(float(d['lat']), float(d['lon'])) for d in all_deliveries]
        # Option A: handoff first then all deliveries
        order_a, swaps_a = self._tsp_2opt_order(handoff_coords, delivery_coords) if delivery_coords else ([], 0)
        ordered_a = [all_deliveries[i] for i in order_a]
        route_a = [depot, handoff_coords] + [delivery_coords[i] for i in order_a] + [depot]
        dist_a = self._route_stats(route_a)
        time_a = sum(self._predict_minutes(route_a[i], route_a[i+1], ordered_a[0] if ordered_a else all_deliveries[0]) for i in range(len(route_a)-1))

        # Option B: deliver own first (for handling company), then handoff, then others
        own = [d for d in all_deliveries if str(d.get('company')) == handling_company]
        other = [d for d in all_deliveries if str(d.get('company')) != handling_company]
        if own:
            own_pts = [(float(d['lat']), float(d['lon'])) for d in own]
            order_own, _ = self._tsp_2opt_order(depot, own_pts)
            pre_coords = [depot] + [own_pts[i] for i in order_own] + [handoff_coords]
            ordered_pre = [own[i] for i in order_own]
        else:
            pre_coords = [depot, handoff_coords]
            ordered_pre = []
        if other:
            other_pts = [(float(d['lat']), float(d['lon'])) for d in other]
            order_other, _ = self._tsp_2opt_order(handoff_coords, other_pts)
            post_coords = [handoff_coords] + [other_pts[i] for i in order_other]
            ordered_post = [other[i] for i in order_other]
        else:
            post_coords = [handoff_coords]
            ordered_post = []
        route_b = pre_coords + post_coords[1:] + [depot]
        ordered_b = ordered_pre + ordered_post
        dist_b = self._route_stats(route_b)
        time_b = sum(self._predict_minutes(route_b[i], route_b[i+1], (ordered_b[0] if ordered_b else (ordered_a[0] if ordered_a else all_deliveries[0]))) for i in range(len(route_b)-1))

        if (dist_b, time_b) < (dist_a, time_a):
            route_coords = route_b
            ordered_deliveries = ordered_b
            handoff_stage = 'mid'
            swaps = swaps_a
        else:
            route_coords = route_a
            ordered_deliveries = ordered_a
            handoff_stage = 'start'
            swaps = swaps_a

        # Record optimization steps
        if swaps:
            self.optimization_steps.append({
                'route_id': f"COLLAB_{opportunity['cluster_id']}",
                'company_id': handling_company,
                'algorithm': 'TSP_2opt',
                'initial_order': 'nearest_neighbor',
                'swaps_made': swaps,
                'final_order': order,
                'deliveries': [d['id'] for d in all_deliveries],
                'handoff_optimization': True
            })

        # Route: depot -> handoff -> deliveries -> depot
        route_coords = [depot, handoff_coords] + [delivery_coords[i] for i in order] + [depot]

        # Calculate route statistics
        total_distance = self._route_stats(route_coords)
        total_time = sum(self._predict_minutes(route_coords[i], route_coords[i+1], ordered_deliveries[0])
                        for i in range(len(route_coords)-1))

        # Add cost calculations
        total_cost = float(self.base_stop_fee * len(all_deliveries) + total_distance * self.base_cost_per_km)

        main_route = {
            'route_id': f"COLLAB_{opportunity['cluster_id']}",
            'type': 'collaboration',
            'handling_company': handling_company,
            'participating_companies': list(cluster_deliveries.keys()),
            'handoff_point': handoff_point,
            'handoff_stage': handoff_stage,
            'deliveries': ordered_deliveries,
            'coordinates': route_coords,
            'total_deliveries': len(all_deliveries),
            'total_distance_km': round(total_distance, 2),
            'total_time_minutes': float(total_time),
            'total_cost_naira': total_cost,
            'collaboration_savings_km': opportunity.get('estimated_savings_km', 0),
            'collaboration_score': opportunity.get('collaboration_score', 0),
            'efficiency_score': max(50.0, min(99.0, 100.0 * len(all_deliveries) / (total_distance + 5.0))),
            'auction': {
                'mechanism': 'vickrey',
                'winner': handling_company,
                'price': auction.get('price', 0.0),
                'bids': auction.get('bids', {}),
            }
        }

        routes = [main_route]

        # Create individual routes for other companies going to handoff point
        for company in cluster_deliveries.keys():
            if company != handling_company:
                other_depot = self._company_depot(company)
                # Route: depot -> handoff -> depot (no deliveries, just handoff)
                handoff_route_coords = [other_depot, handoff_coords, other_depot]
                handoff_distance = self._route_stats(handoff_route_coords)
                handoff_time = sum(self._predict_minutes(handoff_route_coords[i], handoff_route_coords[i+1],
                                                       cluster_deliveries[company][0] if cluster_deliveries[company] else {'package_weight': 0})
                                 for i in range(len(handoff_route_coords)-1))
                handoff_cost = float(self.base_stop_fee * 0 + handoff_distance * self.base_cost_per_km)  # No stops, just travel

                handoff_route = {
                    'route_id': f"HANDOFF_{company[:3].upper()}_{opportunity['cluster_id']}",
                    'type': 'handoff',
                    'company_id': company,
                    'handoff_point': handoff_point,
                    'deliveries': [],  # No deliveries, just going to handoff
                    'coordinates': handoff_route_coords,
                    'total_deliveries': 0,
                    'total_distance_km': round(handoff_distance, 2),
                    'total_time_minutes': float(handoff_time),
                    'total_cost_naira': handoff_cost,
                    'efficiency_score': 80.0  # Standard efficiency for handoff routes
                }
                routes.append(handoff_route)

        return routes

    def _create_routes_for_deliveries(self, deliveries: List[Dict]) -> List[Dict]:
        """Create individual routes for remaining deliveries"""
        routes = []
        deliveries_by_company = {}
        
        for d in deliveries:
            company = d.get('company', 'mainland_movers')
            if company not in deliveries_by_company:
                deliveries_by_company[company] = []
            deliveries_by_company[company].append(d)
        
        route_index = 1
        for company_id, company_deliveries in deliveries_by_company.items():
            if not company_deliveries:
                continue

            depot = self._company_depot(company_id)
            points = [(float(d['lat']), float(d['lon'])) for d in company_deliveries]
            order, swaps = self._tsp_2opt_order(depot, points)
            route_coords = [depot] + [points[i] for i in order] + [depot]

            # Record optimization steps
            if swaps:
                self.optimization_steps.append({
                    'route_id': f"{company_id[:3].upper()}_INDIVIDUAL_{route_index:02d}",
                    'company_id': company_id,
                    'algorithm': 'TSP_2opt',
                    'initial_order': 'nearest_neighbor',
                    'swaps_made': swaps,
                    'final_order': order,
                    'deliveries': [d['id'] for d in company_deliveries]
                })

            total_distance = self._route_stats(route_coords)
            total_time = sum(self._predict_minutes(route_coords[i], route_coords[i+1], company_deliveries[0])
                           for i in range(len(route_coords)-1))

            route = {
                'route_id': f"{company_id[:3].upper()}_INDIVIDUAL_{route_index:02d}",
                'type': 'individual',
                'company_id': company_id,
                'deliveries': [company_deliveries[i] for i in order],
                'coordinates': route_coords,
                'total_deliveries': len(company_deliveries),
                'total_distance_km': round(total_distance, 2),
                'total_time_minutes': float(total_time)
            }
            routes.append(route)
            route_index += 1
        
        return routes

    def create_optimized_routes(self, use_collaboration: bool = True) -> List[Dict]:
        # Ensure required defaults exist for long-lived instances
        self._ensure_runtime_defaults()
        """
        Build optimized routes for all deliveries.
        If use_collaboration=True, uses clustering and collaboration.
        If use_collaboration=False, uses traditional per-company routing.
        Returns list of route dicts; also populates optimized_routes and optimization_results.
        """
        # Clear previous optimization steps and any cached structures so each run
        # re-optimizes with ALL current deliveries (including newly added ones).
        self.optimization_steps = []
        # Reset caches that may short-circuit recomputation between runs
        self.delivery_clusters = []
        self.collaboration_opportunities = []
        self.individual_routes = []
        self.collaboration_routes = []
        self.collaboration_handoffs = []
        self.optimized_routes = []
        self.route_plan_variants = []

        if not self.deliveries:
            self.optimized_routes = []
            self.optimization_results = {"total_routes": 0, "total_deliveries": 0,
                                          "total_distance_km": 0.0, "total_time_minutes": 0.0,
                                          "total_cost_naira": 0.0, "average_deliveries_per_route": 0.0,
                                          "collaboration_enabled": False, "clusters_found": 0,
                                          "collaboration_opportunities": 0, "estimated_savings_km": 0.0,
                                          "optimization_steps": []}
            return []

        if use_collaboration:
            # Build explicit collaboration + handoff routes for visualization
            # Primary plan (Plan 1)
            routes = self.build_collaboration_routes()
            # Also compute up to one alternate collaboration plan (Plan 2)
            try:
                # Collect baseline handoff points from Plan 1 to enforce diversity in Plan 2
                baseline_points: List[Tuple[float, float]] = []
                for r in routes:
                    if r.get('type') == 'collaboration':
                        hp = r.get('handoff_point') or {}
                        lat = hp.get('lat'); lon = hp.get('lon')
                        if lat is not None and lon is not None:
                            baseline_points.append((float(lat), float(lon)))
                # Ask for a variant that avoids baseline swap points within ~1km (configurable)
                alt_routes = self._build_collaboration_routes_for_variant(variant_index=1,
                                                                         avoid_points=baseline_points,
                                                                         diversity_radius_km=1.0)
                self.route_plan_variants = [routes, alt_routes]
            except Exception:
                self.route_plan_variants = [routes]
        else:
            # Use traditional per-company routing
            routes = self._create_individual_company_routes()
            self.route_plan_variants = [routes]

        # Calculate overall statistics
        total_distance_km = sum(r.get("total_distance_km", 0) for r in routes)
        total_time_minutes = sum(r.get("total_time_minutes", 0) for r in routes)
        total_cost_naira = sum(r.get("total_cost_naira", 0) for r in routes)
        total_deliveries = sum(r.get("total_deliveries", 0) for r in routes)

        # Calculate collaboration statistics
        collaboration_stats = {}
        if use_collaboration:
            collaboration_stats = {
                "collaboration_enabled": True,
                "clusters_found": len(self.delivery_clusters),
                "collaboration_opportunities": len(self.collaboration_opportunities),
                "estimated_savings_km": sum(op.get("estimated_savings_km", 0) for op in self.collaboration_opportunities),
                "collaboration_routes": len([r for r in routes if r.get("type") == "collaboration"]),
                "individual_routes": len([r for r in routes if r.get("type") == "individual"])
            }
        else:
            collaboration_stats = {
                "collaboration_enabled": False,
                "clusters_found": 0,
                "collaboration_opportunities": 0,
                "estimated_savings_km": 0.0
            }

        self.optimized_routes = routes
        self.optimization_results = {
            "total_routes": len(routes),
            "total_deliveries": total_deliveries,
            "total_distance_km": round(total_distance_km, 2),
            "total_time_minutes": float(total_time_minutes),
            "total_cost_naira": float(total_cost_naira),
            "average_deliveries_per_route": float(total_deliveries / len(routes) if routes else 0.0),
            **collaboration_stats
        }
        return routes

    def _create_collaborative_routes(self) -> List[Dict]:
        """Create routes using clustering and collaboration based on FLOWCHART2.py approach"""
        # Step 1: Cluster deliveries with KMeans
        self.cluster_deliveries()

        # Step 2: Analyze collaboration (reassign orders within clusters)
        updated_deliveries, handoffs = self.analyze_collaboration()

        # Step 3: Create routes with updated deliveries
        routes = self._create_routes_for_deliveries(updated_deliveries)

        # Store handoffs for visualization
        self.collaboration_handoffs = handoffs

        # Add cost calculations and mark as collaboration routes
        for route in routes:
            if "total_cost_naira" not in route:
                distance = route.get("total_distance_km", 0)
                deliveries = route.get("total_deliveries", 0)
                route["total_cost_naira"] = float(self.base_stop_fee * deliveries + distance * self.base_cost_per_km)

                # Add efficiency score
                if distance > 0:
                    route["efficiency_score"] = max(50.0, min(99.0, 100.0 * deliveries / (distance + 5.0)))
                else:
                    route["efficiency_score"] = 95.0

        return routes

    def _create_individual_company_routes(self) -> List[Dict]:
        """Create traditional per-company routes (original logic)"""
        routes: List[Dict] = []
        
        # Group by company
        deliveries_by_company: Dict[str, List[Dict]] = {}
        for d in self.deliveries:
            deliveries_by_company.setdefault(d.get("company", "mainland_movers"), []).append(d)

        route_index = 1
        for company_id, group in deliveries_by_company.items():
            depot = self._company_depot(company_id)
            points = [(float(d["lat"]), float(d["lon"])) for d in group]
            order, swaps = self._tsp_2opt_order(depot, points)

            # Record optimization steps
            if swaps:
                self.optimization_steps.append({
                    'route_id': f"{company_id[:3].upper()}_ROUTE_{route_index:02d}",
                    'company_id': company_id,
                    'algorithm': 'TSP_2opt',
                    'initial_order': 'nearest_neighbor',
                    'swaps_made': swaps,
                    'final_order': order,
                    'deliveries': [d['id'] for d in group]
                })

            # Determine vehicle type for the route using max weight or preference
            max_w = max(float(d.get("package_weight", 0.0)) for d in group) if group else 0.0
            # Use first non-'Any' preference
            pref = next((d.get("vehicle_preference") for d in group if d.get("vehicle_preference") and d.get("vehicle_preference") != "Any"), None)
            vehicle_type = self._vehicle_type_for(max_w, pref)

            route_coords: List[Tuple[float, float]] = [depot] + [points[i] for i in order] + [depot]

            # Compute leg-by-leg predictions
            leg_rows = []
            cur = route_coords[0]
            seq_num = 1
            route_time_min = 0.0
            route_dist_km = 0.0
            route_cost = 0.0

            for idx in range(1, len(route_coords)):
                nxt = route_coords[idx]
                # Map index to delivery
                if idx == len(route_coords) - 1:
                    # returning to depot, reuse last delivery metadata
                    dmeta = group[order[-1]]
                    delivery_id = dmeta["id"]
                    pkg_w = float(dmeta.get("package_weight", 0.0))
                    pkg_size = dmeta.get("package_size", "medium")
                else:
                    dmeta = group[order[idx-1]]
                    delivery_id = dmeta["id"]
                    pkg_w = float(dmeta.get("package_weight", 0.0))
                    pkg_size = dmeta.get("package_size", "medium")

                # predict minutes using model with dmeta context
                dmeta_local = dmeta.copy()
                dmeta_local["vehicle_preference"] = pref
                dmeta_local["package_size"] = pkg_size
                minutes = self._predict_minutes(cur, nxt, dmeta_local)
                dist_km = haversine_km(cur, nxt)

                # cost estimation
                leg_cost = self.base_stop_fee + dist_km * self.base_cost_per_km

                leg_rows.append({
                    "sequence": seq_num if idx < len(route_coords)-1 else seq_num,  # depot return gets a number too
                    "delivery_id": delivery_id,
                    "distance_from_previous": round(dist_km, 3),
                    "estimated_time": float(minutes),
                    "package_weight": pkg_w,
                })
                seq_num += 1
                route_time_min += float(minutes)
                route_dist_km += dist_km
                route_cost += leg_cost
                cur = nxt

            route_id = f"{company_id[:3].upper()}_ROUTE_{route_index:02d}"
            route_index += 1

            route_dict = {
                "route_id": route_id,
                "type": "individual",
                "company_id": company_id,
                "vehicle_type": vehicle_type,
                "deliveries": [group[i] for i in order],  # actual delivery objects in optimized order
                "coordinates": route_coords,
                "total_deliveries": len(group),
                "total_distance_km": round(route_dist_km, 2),
                "total_time_minutes": float(route_time_min),
                "total_cost_naira": float(route_cost),
                "efficiency_score": max(50.0, min(99.0, 100.0 * len(group) / (route_dist_km + 5.0))),
            }
            routes.append(route_dict)

        return routes

    def get_route_visualization_data(self, route_type: str = "collaboration") -> Dict:
        """
        Get data formatted for map visualization.
        route_type: "collaboration" or "individual"
        """
        if route_type == "collaboration":
            routes = self.collaboration_routes if self.collaboration_routes else self.optimized_routes
            handoffs = self.collaboration_handoffs
        else:
            if not self.individual_routes:
                # Generate individual routes from original deliveries (before collaboration modifications)
                if self.original_deliveries:
                    # Temporarily replace deliveries with original ones
                    temp_deliveries = self.deliveries
                    self.deliveries = self.original_deliveries.copy()
                    self.individual_routes = self._create_individual_company_routes()
                    self.deliveries = temp_deliveries
                else:
                    # Fallback to current deliveries if no originals
                    self.individual_routes = self._create_individual_company_routes()
            routes = self.individual_routes
            handoffs = []

        visualization_data = {
            "routes": routes,
            "route_variants": self.route_plan_variants if getattr(self, 'route_plan_variants', None) else [routes],
            "clusters": self.delivery_clusters,
            "collaboration_opportunities": self.collaboration_opportunities,
            "companies": self.companies,
            "exchange_points": self.exchange_points,
            "handoffs": handoffs,
            "route_type": route_type,
            "statistics": self.optimization_results
        }

        return visualization_data

    # --------------------------------------------
    # Federated Learning with Differential Privacy
    # --------------------------------------------
    def federated_aggregate_with_dp(self, updates: List[np.ndarray], epsilon: float = 1.0,
                                    delta: float = 1e-5, clip_C: float = 1.0,
                                    seed: Optional[int] = None) -> Optional[np.ndarray]:
        """Aggregate client updates with Gaussian DP noise.

        Steps:
          - Per-update L2 clipping to clip_C
          - Sum clipped updates
          - Add Gaussian noise N(0, sigma^2 I) with sigma = clip_C * sqrt(2 ln(1.25/delta)) / epsilon
          - Return averaged noisy update
        Returns None if no updates.
        """
        if not updates:
            return None
        rng = np.random.default_rng(seed)
        clipped: List[np.ndarray] = []
        for u in updates:
            try:
                v = np.array(u, dtype=float)
                norm = np.linalg.norm(v)
                if norm > clip_C and norm > 0:
                    v = v * (clip_C / norm)
                clipped.append(v)
            except Exception:
                continue
        if not clipped:
            return None
        summed = np.sum(clipped, axis=0)
        # Compute sigma per DP-SGD analysis
        try:
            sigma = clip_C * math.sqrt(2.0 * math.log(1.25 / max(delta, 1e-12))) / max(epsilon, 1e-6)
        except Exception:
            sigma = 1.0
        noise = rng.normal(loc=0.0, scale=sigma, size=summed.shape)
        noisy_sum = summed + noise
        return noisy_sum / float(len(clipped))
    def _ensure_runtime_defaults(self) -> None:
        """Ensure critical attributes exist for long-lived instances created before
        newer fields were added (backward/forward compatibility)."""
        # Cost/time defaults
        if not hasattr(self, 'base_cost_per_km'):
            self.base_cost_per_km = 200.0
        if not hasattr(self, 'base_stop_fee'):
            self.base_stop_fee = 150.0
        if not hasattr(self, 'default_weather'):
            self.default_weather = 'sunny'
        if not hasattr(self, 'default_traffic'):
            self.default_traffic = 'moderate'
        # Clustering/collaboration thresholds
        if not hasattr(self, 'cluster_radius_km'):
            self.cluster_radius_km = 5.0
        if not hasattr(self, 'min_cluster_size'):
            self.min_cluster_size = 2
        if not hasattr(self, 'collaboration_threshold_km'):
            self.collaboration_threshold_km = 10.0
        # Company network
        if not hasattr(self, 'companies') or not isinstance(getattr(self, 'companies'), dict) or not self.companies:
            try:
                self.companies = self._default_companies()
            except Exception:
                self.companies = {}
        # Exchange points list
        if not hasattr(self, 'exchange_points') or not isinstance(getattr(self, 'exchange_points'), list):
            try:
                self.exchange_points = self._default_exchange_points()
            except Exception:
                self.exchange_points = []
        # Diversity thresholds / settings
        if not hasattr(self, 'handoff_existing_stop_threshold_km'):
            self.handoff_existing_stop_threshold_km = 0.75
