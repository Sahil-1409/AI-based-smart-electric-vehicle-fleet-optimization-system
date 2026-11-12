
"""Smart EV Fleet - demo backend and ESP32-ready GPS ingestion API."""
import math
import os
import random
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'fleet.db'
DB.parent.mkdir(exist_ok=True)
API_KEY = os.getenv('FLEET_API_KEY', 'demo-esp32-key')
lock = threading.RLock()

def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def fetch(query, params=()):
    with lock, conn() as c:
        return [dict(r) for r in c.execute(query, params).fetchall()]

def execute(query, params=()):
    with lock, conn() as c:
        cur = c.execute(query, params)
        c.commit()
        return cur.lastrowid

def distance(a,b,c,d):
    p1,p2 = math.radians(a), math.radians(c)
    dp=math.radians(c-a); dl=math.radians(d-b)
    x=math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return round(6371*2*math.atan2(math.sqrt(x),math.sqrt(1-x)),2)

SEED = [
 ('EV-101','Alpha Delivery',30.9009,75.8573,84,38,'available', 'demo'),
 ('EV-102','Beta Cargo',30.8895,75.8248,67,24,'available', 'demo'),
 ('EV-103','Gamma Express',30.9186,75.8772,19,12,'available', 'demo'),
 ('EV-104','Delta Logistics',30.8738,75.8567,92,33,'available', 'demo'),
 ('EV-105','Echo Pickup',30.9255,75.8282,54,28,'available', 'demo'),
 ('EV-106','Foxtrot Support',30.8920,75.8930,76,18,'available', 'demo')]

def init():
    with lock, conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS vehicles (
          id TEXT PRIMARY KEY, name TEXT, lat REAL, lng REAL, battery REAL,
          speed REAL, status TEXT, source TEXT, last_seen INTEGER);
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
          pickup_label TEXT, pickup_lat REAL, pickup_lng REAL,
          drop_label TEXT, drop_lat REAL, drop_lng REAL,
          vehicle_id TEXT, status TEXT NOT NULL, priority TEXT NOT NULL,
          created_at INTEGER, notes TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS alerts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id TEXT,
          kind TEXT, message TEXT, level TEXT, created_at INTEGER, resolved INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER, message TEXT);
        ''')
        if not c.execute('SELECT 1 FROM vehicles LIMIT 1').fetchone():
            c.executemany('INSERT INTO vehicles VALUES (?,?,?,?,?,?,?,?,?)',
                 [(*s,int(time.time())) for s in SEED])
            c.execute('INSERT INTO events(at,message) VALUES (?,?)',(int(time.time()),'Demo fleet initialized'))
        c.commit()
    check_low_battery()

def log(message): execute('INSERT INTO events(at,message) VALUES (?,?)',(int(time.time()),message))

def alert(vehicle_id, kind, message, level='warning'):
    old=fetch('SELECT id FROM alerts WHERE vehicle_id=? AND kind=? AND resolved=0',(vehicle_id,kind))
    if not old:
        execute('INSERT INTO alerts(vehicle_id,kind,message,level,created_at) VALUES (?,?,?,?,?)',(vehicle_id,kind,message,level,int(time.time())))
        log(message)

def check_low_battery():
    for v in fetch('SELECT * FROM vehicles'):
        if v['battery'] <= 20:
            alert(v['id'],'low_battery',f"{v['id']} has low battery ({v['battery']:.0f}%)",'danger')
        else:
            execute("UPDATE alerts SET resolved=1 WHERE vehicle_id=? AND kind='low_battery' AND resolved=0",(v['id'],))

init()
app = FastAPI(title='Smart EV Fleet API', version='1.0.0')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

class Telemetry(BaseModel):
    vehicle_id: str = Field(min_length=2, max_length=40)
    latitude: float = Field(ge=-90,le=90)
    longitude: float = Field(ge=-180,le=180)
    speed: float = Field(default=0,ge=0,le=250)
    battery: float | None = Field(default=None,ge=0,le=100)

class TaskIn(BaseModel):
    title: str = Field(min_length=2,max_length=120)
    pickup_label: str = 'Pickup'
    pickup_lat: float = Field(ge=-90,le=90)
    pickup_lng: float = Field(ge=-180,le=180)
    drop_label: str = 'Destination'
    drop_lat: float = Field(ge=-90,le=90)
    drop_lng: float = Field(ge=-180,le=180)
    vehicle_id: str | None = None
    priority: str = 'Normal'
    notes: str = ''

class Incident(BaseModel):
    vehicle_id: str
    reason: str = 'Vehicle breakdown'

class StatusUpdate(BaseModel):
    status: str

@app.get('/')
def index(): return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/overview')
def overview():
    vs=fetch('SELECT * FROM vehicles ORDER BY id')
    ts=fetch('SELECT * FROM tasks ORDER BY id DESC')
    aa=fetch('SELECT * FROM alerts WHERE resolved=0 ORDER BY id DESC')
    return {'vehicles':vs,'tasks':ts,'alerts':aa,'events':fetch('SELECT * FROM events ORDER BY id DESC LIMIT 15'),
            'stats':{'vehicles':len(vs),'available':sum(v['status']=='available' and v['battery']>20 for v in vs),
                     'on_trip':sum(v['status']=='on_trip' for v in vs),'active_tasks':sum(t['status'] in ('assigned','in_progress') for t in ts),
                     'low_battery':sum(v['battery']<=20 for v in vs),'alerts':len(aa)}}

@app.get('/api/nearby')
def nearby(lat:float,lng:float, exclude:str='', min_battery:float=25):
    vs=[v for v in fetch('SELECT * FROM vehicles') if v['id']!=exclude and v['status']=='available' and v['battery']>=min_battery]
    return sorted([{**v,'distance_km':distance(lat,lng,v['lat'],v['lng'])} for v in vs],key=lambda x:x['distance_km'])

@app.post('/api/tasks')
def create_task(t:TaskIn):
    if t.priority not in ('Low','Normal','High','Urgent'): raise HTTPException(400,'Invalid priority')
    vehicle_id=t.vehicle_id
    if vehicle_id:
        v=fetch('SELECT * FROM vehicles WHERE id=?',(vehicle_id,))
        if not v: raise HTTPException(404,'Vehicle not found')
        if v[0]['status']!='available' or v[0]['battery']<=20: raise HTTPException(400,'Vehicle not available / battery too low')
    else:
        candidates=nearby(t.pickup_lat,t.pickup_lng)
        vehicle_id=candidates[0]['id'] if candidates else None
    status='assigned' if vehicle_id else 'pending'
    tid=execute('''INSERT INTO tasks(title,pickup_label,pickup_lat,pickup_lng,drop_label,drop_lat,drop_lng,vehicle_id,status,priority,created_at,notes)
       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(t.title,t.pickup_label,t.pickup_lat,t.pickup_lng,t.drop_label,t.drop_lat,t.drop_lng,vehicle_id,status,t.priority,int(time.time()),t.notes))
    if vehicle_id: execute('UPDATE vehicles SET status=? WHERE id=?',('on_trip',vehicle_id))
    log(f'Task #{tid} {status}' + (f' to {vehicle_id}' if vehicle_id else ' (no available EV)'))
    return {'id':tid,'status':status,'vehicle_id':vehicle_id}

@app.post('/api/tasks/{tid}/complete')
def complete_task(tid:int):
    task=fetch('SELECT * FROM tasks WHERE id=?',(tid,))
    if not task:raise HTTPException(404,'Task not found')
    t=task[0]
    if t['status'] in ('completed','cancelled'):raise HTTPException(400,'Task already closed')
    execute('UPDATE tasks SET status=? WHERE id=?',('completed',tid))
    if t['vehicle_id']:
        execute("UPDATE vehicles SET status='available' WHERE id=? AND status='on_trip'",(t['vehicle_id'],))
    log(f'Task #{tid} completed')
    return {'ok':True}

@app.post('/api/incidents')
def incident(e:Incident):
    vs=fetch('SELECT * FROM vehicles WHERE id=?',(e.vehicle_id,))
    if not vs:raise HTTPException(404,'Vehicle not found')
    v=vs[0]
    execute("UPDATE vehicles SET status='breakdown',speed=0 WHERE id=?",(e.vehicle_id,))
    alert(e.vehicle_id,'breakdown',f'{e.vehicle_id}: {e.reason}','danger')
    affected=fetch("SELECT * FROM tasks WHERE vehicle_id=? AND status IN ('assigned','in_progress')",(e.vehicle_id,))
    reroutes=[]
    for t in affected:
        choices=nearby(v['lat'],v['lng'],exclude=e.vehicle_id)
        if choices:
            substitute=choices[0]
            execute('UPDATE tasks SET vehicle_id=?,status=? WHERE id=?',(substitute['id'],'assigned',t['id']))
            execute("UPDATE vehicles SET status='on_trip' WHERE id=?",(substitute['id'],))
            log(f"RESCUE: Task #{t['id']} reassigned {e.vehicle_id} → {substitute['id']} ({substitute['distance_km']} km away)")
            reroutes.append({'task_id':t['id'],'replacement':substitute['id'],'distance_km':substitute['distance_km']})
        else:
            execute("UPDATE tasks SET vehicle_id=NULL,status='pending' WHERE id=?",(t['id'],))
            log(f"Task #{t['id']} pending: no rescue vehicle available")
            reroutes.append({'task_id':t['id'],'replacement':None})
    return {'breakdown_vehicle':e.vehicle_id,'reassignments':reroutes}

@app.post('/api/vehicles/{vehicle_id}/status')
def status(vehicle_id:str,s:StatusUpdate):
    if s.status not in ('available','charging','maintenance','breakdown'):raise HTTPException(400,'Invalid status')
    if not fetch('SELECT id FROM vehicles WHERE id=?',(vehicle_id,)):raise HTTPException(404,'Vehicle not found')
    if fetch("SELECT id FROM tasks WHERE vehicle_id=? AND status IN ('assigned','in_progress')",(vehicle_id,)):
        raise HTTPException(409,'Complete or rescue active tasks first')
    execute('UPDATE vehicles SET status=?,speed=0 WHERE id=?',(s.status,vehicle_id))
    if s.status=='available':execute("UPDATE alerts SET resolved=1 WHERE vehicle_id=? AND kind='breakdown'",(vehicle_id,))
    log(f'{vehicle_id} status → {s.status}')
    return {'ok':True}

@app.post('/api/demo/tick')
def demo_tick():
    for v in fetch("SELECT * FROM vehicles WHERE source='demo'"):
        if v['status'] in ('breakdown','maintenance','charging'):continue
        sp=round(random.uniform(12,48),1) if v['status']=='on_trip' else round(random.uniform(0,16),1)
        lat=v['lat']+random.uniform(-0.00035,0.00035)
        lng=v['lng']+random.uniform(-0.00035,0.00035)
        batt=max(0,round(v['battery']-random.uniform(0.02,0.16),2))
        execute('UPDATE vehicles SET lat=?,lng=?,speed=?,battery=?,last_seen=? WHERE id=?',(lat,lng,sp,batt,int(time.time()),v['id']))
    check_low_battery()
    return {'ok':True,'time':int(time.time())}

@app.post('/api/telemetry')
def telemetry(t:Telemetry,x_api_key:str|None=Header(default=None)):
    # if x_api_key != API_KEY:raise HTTPException(401,'Invalid X-API-Key')
    old=fetch('SELECT * FROM vehicles WHERE id=?',(t.vehicle_id,))
    if old:
        battery=t.battery if t.battery is not None else old[0]['battery']
        execute('UPDATE vehicles SET lat=?,lng=?,speed=?,battery=?,source=?,last_seen=? WHERE id=?',
                (t.latitude,t.longitude,t.speed,battery,'hardware',int(time.time()),t.vehicle_id))
    else:
        execute('INSERT INTO vehicles VALUES (?,?,?,?,?,?,?,?,?)',
                (t.vehicle_id,t.vehicle_id,t.latitude,t.longitude,t.battery if t.battery is not None else 100,t.speed,'available','hardware',int(time.time())))
        log(f'New hardware vehicle connected: {t.vehicle_id}')
    check_low_battery()
    return {'ok':True,'vehicle_id':t.vehicle_id}

@app.get('/health')
def health():return {'status':'ok'}

# Optional, separately configured Google Maps Platform integrations.
# Keep server-side keys out of the browser and source-controlled files.
import json as _json
import urllib.request as _urlreq
import urllib.error as _urlerror

@app.get('/api/maps/config')
def maps_config():
    return {'browser_key': os.getenv('GOOGLE_MAPS_BROWSER_KEY', ''),
            'places_ready': bool(os.getenv('GOOGLE_PLACES_SERVER_KEY')),
            'routes_ready': bool(os.getenv('GOOGLE_ROUTES_SERVER_KEY'))}

# @app.get('/api/charging/nearby')
# def charging_nearby(lat:float, lng:float, radius:int=5000):
#     if not -90 <= lat <= 90 or not -180 <= lng <= 180:
#         raise HTTPException(400,'Invalid coordinates')
#     key=os.getenv('GOOGLE_PLACES_SERVER_KEY','')
#     if not key: return {'configured':False,'stations':[], 'message':'Set GOOGLE_PLACES_SERVER_KEY to search real charging stations.'}
#     payload={'includedTypes':['electric_vehicle_charging_station'], 'maxResultCount':15,
#              'rankPreference':'DISTANCE',
#              'locationRestriction':{'circle':{'center':{'latitude':lat,'longitude':lng},'radius':min(max(radius,100),30000)}}}
#     req=_urlreq.Request('https://places.googleapis.com/v1/places:searchNearby',data=_json.dumps(payload).encode(),method='POST',
#         headers={'Content-Type':'application/json','X-Goog-Api-Key':key,
#                  'X-Goog-FieldMask':'places.id,places.displayName,places.location,places.formattedAddress,places.googleMapsUri'})
#     try:
#         with _urlreq.urlopen(req,timeout=14) as response: data=_json.load(response)
#     except (_urlerror.HTTPError,_urlerror.URLError,TimeoutError) as exc:
#         raise HTTPException(502,'Google Places request failed; check API permissions, key, quota, billing and network.') from exc
#     stations=[]
#     for p in data.get('places',[]):
#         loc=p.get('location',{})
#         if 'latitude' not in loc or 'longitude' not in loc:continue
#         stations.append({'id':p.get('id',''),'name':p.get('displayName',{}).get('text','Charging station'),
#                          'address':p.get('formattedAddress',''), 'lat':loc['latitude'],'lng':loc['longitude'],
#                          'maps_url':p.get('googleMapsUri',''),
#                          'distance_km':distance(lat,lng,loc['latitude'],loc['longitude'])})
#     return {'configured':True,'stations':sorted(stations,key=lambda x:x['distance_km']),'message':'Live Google Places search results; charger availability is not verified.'}


# yaha se naya update kiya

# FREE OPENSTREETMAP CHARGING STATIONS
import math
import json
import urllib.request
import urllib.parse

@app.get("/api/charging/nearby")
def charging_nearby(
    lat: float,
    lng: float,
    radius: int = 5000
):
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(
            status_code=400,
            detail="Invalid GPS coordinates"
        )

    radius = max(100, min(radius, 30000))

    query = f"""
    [out:json][timeout:25];
    (
      nwr["amenity"="charging_station"]
      (around:{radius},{lat},{lng});
    );
    out center;
    """

    url = "https://overpass-api.de/api/interpreter"

    try:
        body = urllib.parse.urlencode(
            {"data": query}
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "User-Agent": "VoltFleetStudentProject/1.0"
            },
            method="POST"
        )

        with urllib.request.urlopen(
            request, timeout=40
        ) as response:
            data = json.load(response)

        stations = []

        for item in data.get("elements", []):
            tags = item.get("tags", {})
            center = item.get("center") or {}

            slat = item.get("lat", center.get("lat"))
            slng = item.get("lon", center.get("lon"))

            if slat is None or slng is None:
                continue

            p1 = math.radians(lat)
            p2 = math.radians(slat)
            dp = math.radians(slat - lat)
            dl = math.radians(slng - lng)

            a = (
                math.sin(dp / 2) ** 2
                + math.cos(p1) * math.cos(p2)
                * math.sin(dl / 2) ** 2
            )

            km = 6371 * 2 * math.asin(
                math.sqrt(min(1, a))
            )

            station_name = (
                tags.get("name")
                or tags.get("operator")
                or "EV Charging Station"
            )

            stations.append({
                "id": f"osm-{item['type']}-{item['id']}",
                "name": station_name,
                "address": ", ".join(filter(None, [
                    tags.get("addr:street"),
                    tags.get("addr:city"),
                    tags.get("addr:state")
                ])) or "Address not listed",
                "lat": slat,
                "lng": slng,
                "distance_km": round(km, 2),
                "maps_url": (
                    "https://www.openstreetmap.org/"
                    f"?mlat={slat}&mlon={slng}"
                    f"#map=16/{slat}/{slng}"
                )
            })

        stations.sort(key=lambda x: x["distance_km"])

        return {
            "configured": True,
            "stations": stations[:30],
            "message": (
                f"Found {len(stations)} charging stations "
                "in OpenStreetMap. "
                "Live availability is not verified."
            )
        }

    except Exception as e:
        return {
            "configured": False,
            "stations": [],
            "message": (
                "OpenStreetMap charging search failed: "
                + str(e)[:180]
            )
        }

# yaha tak naya update kiya
class RouteRequest(BaseModel):
    origin_lat:float=Field(ge=-90,le=90)
    origin_lng:float=Field(ge=-180,le=180)
    destination_lat:float=Field(ge=-90,le=90)
    destination_lng:float=Field(ge=-180,le=180)
    preference:str='TRAFFIC_AWARE'

@app.post('/api/maps/route')
def google_route(r:RouteRequest):
    key=os.getenv('GOOGLE_ROUTES_SERVER_KEY','')
    if not key: return {'configured':False,'message':'Set GOOGLE_ROUTES_SERVER_KEY for Google road routes.'}
    payload={'origin':{'location':{'latLng':{'latitude':r.origin_lat,'longitude':r.origin_lng}}},
             'destination':{'location':{'latLng':{'latitude':r.destination_lat,'longitude':r.destination_lng}}},
             'travelMode':'DRIVE','routingPreference':'TRAFFIC_AWARE', 'computeAlternativeRoutes':True,
             'languageCode':'en-US','units':'METRIC'}
    req=_urlreq.Request('https://routes.googleapis.com/directions/v2:computeRoutes',method='POST',data=_json.dumps(payload).encode(),
       headers={'Content-Type':'application/json','X-Goog-Api-Key':key,
                'X-Goog-FieldMask':'routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.description'})
    try:
        with _urlreq.urlopen(req,timeout=14) as response: data=_json.load(response)
    except (_urlerror.HTTPError,_urlerror.URLError,TimeoutError) as exc:
        raise HTTPException(502,'Google Routes request failed; check key, API activation, quota or billing.') from exc
    return {'configured':True,'routes':[{'distance_km':round(x.get('distanceMeters',0)/1000,2),
       'duration_seconds':float(x.get('duration','0s').rstrip('s')),
       'encoded_polyline':x.get('polyline',{}).get('encodedPolyline',''),
       'description':x.get('description','Google route')} for x in data.get('routes',[])]}
