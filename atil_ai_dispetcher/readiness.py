"""Use the same eligibility rules for plan review and candidate ranking."""
from datetime import date
from atil_ai_dispetcher.vehicle_selection import queries, ranker, rules, config

def review(plan, on_date):
    if isinstance(on_date,str):on_date=date.fromisoformat(on_date)
    vehicles=queries.fetch_vehicles(on_date=on_date.isoformat(),limit=1000)
    drivers=queries.fetch_drivers(on_date=on_date.isoformat(),history_days=config.HISTORY_DAYS,limit=1000)
    by_vehicle={r['vehicle_id']:r for r in vehicles}
    by_driver={r['driver_id']:r for r in drivers}
    reviews=[];used_drivers={}
    for route in plan.get('routes',[]):
        blockers=[];unknown=[]
        v=by_vehicle.get(route['vehicle_id']);d=by_driver.get(route.get('driver_id'))
        demand={'cargo_weight_kg':route.get('max_load_kg'),'window_from':route.get('starts_at'),'window_to':route.get('ends_at')}
        if v:
            evaluated=ranker._evaluate_vehicle(v,demand,on_date)
            blockers+=evaluated.blockers
            if route.get('max_load_kg',0)>0 and not route.get('capacity_kg'):unknown.append('Yuk sig‘imi tasdiqlanmagan')
        else:blockers.append('VEHICLE_NOT_FOUND')
        if d:
            evaluated=ranker._evaluate_driver(d,demand,on_date,require_medical=True)
            blockers+=evaluated.blockers
            if not d.get('license_valid_until'):unknown.append('Guvohnoma muddati noma’lum')
            if not d.get('license_categories'):unknown.append('Haydovchi toifalari noma’lum')
            # Conservatively require a separate dispatch review when one driver
            # appears on several vehicle routes; don't imply a global driver solver.
            if route['driver_id'] in used_drivers:blockers.append('DRIVER_MULTIPLE_ROUTES')
            used_drivers[route['driver_id']]=True
        else:blockers.append('DRIVER_NOT_FOUND')
        reviews.append({'vehicle_id':route['vehicle_id'],'plate_number':route.get('plate_number'),
                        'driver_id':route.get('driver_id'),'blockers':sorted(set(blockers)),'unknown':unknown,
                        'ready':not blockers and not unknown})
    return {'routes':reviews,'ready':bool(reviews) and all(r['ready'] for r in reviews),
            'scope':'Transport va haydovchi qoidalari qayta tekshirildi. Transportlararo haydovchi almashinuvi optimizatsiya qilinmagan.',
            'on_date':on_date.isoformat()}
