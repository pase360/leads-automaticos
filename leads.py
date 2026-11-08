# Genera leads reales por corrida y los carga en Odoo respetando la arquitectura original.
# Solo usa la libreria estandar de Python: no hay nada que instalar.
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

# ---------- Configuracion (las claves vienen de los Secrets de GitHub) ----------
# Se elimina GEOAPIFY_KEY ya que Overpass API es gratuito y sin llaves.
ODOO_URL = os.environ.get('ODOO_URL', '').strip().rstrip('/')
ODOO_DB = os.environ.get('ODOO_DB', '').strip()
ODOO_USER = os.environ.get('ODOO_USER', '').strip()
ODOO_KEY = os.environ.get('ODOO_KEY', '').strip()
ODOO_ETAPA = os.environ.get('ODOO_ETAPA', '').strip()
DRY_RUN = os.environ.get('DRY_RUN', '0') == '1'

CIUDAD = 'Córdoba, Argentina'
TOTAL_COMERCIOS = 45
TOTAL_INSTITUCIONES = 5

# Límites geográficos reales de Córdoba para la consulta del mapa
LAT_MIN, LON_MIN, LAT_MAX, LON_MAX = -31.4700, -64.2500, -31.3500, -64.1200

# Mapeo de rubros compatibles con el mapa público (OpenStreetMap)
RUBROS_OSM = {
    'Carnicería': 'butcher',
    'Panadería': 'bakery',
    'Zapatería': 'shoes',
    'Peluquería': 'hairdresser',
    'Ropa': 'clothes',
    'Supermercado': 'supermarket',
    'Café': 'cafe',
    'Restaurante': 'restaurant',
    'Gimnasio': 'fitness_centre',
    'Farmacia': 'pharmacy',
    'Florería': 'florist',
    'Óptica': 'optician'
}

PALABRAS_INSTITUCION = ['sindicato', 'asociacion', 'colegio', 'camara', 'federacion',
                        'mutual', 'cooperativa', 'universidad', 'club', 'gremio', 'union']


# ---------- Utilidades ----------
def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub('[ ]+', ' ', s.lower().strip())


def http_get(url, timeout=15):
    # User-Agent emulado para evitar bloqueos HTTP 405/403 en servidores públicos de mapas
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(600000)
        charset = r.headers.get_content_charset() or 'utf-8'
    return data.decode(charset, errors='ignore')


class Vistos:
    def __init__(self):
        self.claves = set()
        self.tels = set()
        self.mails = set()

    @staticmethod
    def _tel(t):
        d = re.sub('[^0-9]', '', t or '')
        return d[-8:] if len(d) >= 8 else ''

    def dup(self, l):
        if norm(l.get('nombre')) + '|' + norm(l.get('direccion')) in self.claves:
            return True
        t = self._tel(l.get('telefono'))
        if t and t in self.tels:
            return True
        m = (l.get('email') or '').lower()
        return bool(m and m in self.mails)

    def add(self, l):
        self.claves.add(norm(l.get('nombre')) + '|' + norm(l.get('direccion')))
        t = self._tel(l.get('telefono'))
        if t:
            self.tels.add(t)
        m = (l.get('email') or '').lower()
        if m:
            self.mails.add(m)


# ---------- Extracción desde Overpass API (OpenStreetMap) ----------
def consultar_mapa(query_osm):
    url_base = "https://overpass-api.de/api/interpreter"
    url_completa = f"{url_base}?data={urllib.parse.quote(query_osm)}"
    
    for intento in range(3):
        try:
            time.sleep(0.5)
            content = http_get(url_completa, 25)
            return json.loads(content).get('elements', [])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(4 * (intento + 1))
                continue
            return []
        except Exception:
            time.sleep(2)
    return []


def procesar_elemento_osm(el, rubro_es, etiqueta):
    tags = el.get('tags', {})
    calle = tags.get('addr:street', '')
    altura = tags.get('addr:housenumber', '')
    direccion = f"{calle} {altura}".strip() if calle else "Córdoba, Argentina"
    
    return {
        'nombre': tags.get('name', ''),
        'telefono': tags.get('phone', tags.get('contact:phone', '')),
        'email': tags.get('email', tags.get('contact:email', '')),
        'direccion': direccion,
        'rubro': rubro_es,
        'barrio': tags.get('addr:suburb', 'Córdoba Centro'),
        'etiqueta': etiqueta,
        'web': tags.get('website', tags.get('contact:website', ''))
    }


def buscar_comercios(vistos):
    condiciones = ""
    for rubro_osm in RUBROS_OSM.values():
        condiciones += f'  node["shop"="{rubro_osm}"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
'
        condiciones += f'  node["amenity"="{rubro_osm}"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
'
    
    query = f"[out:json][timeout:30];
(
{condiciones});
out body;"
    elementos = consultar_mapa(query)
    
    candidatos = []
    for el in elementos:
        tags = el.get('tags', {})
        if not tags.get('name'):
            continue
        
        tipo_comercio = tags.get('shop', tags.get('amenity', ''))
        rubro_es = next((k for k, v in RUBROS_OSM.items() if v == tipo_comercio), 'Comercio')
        
        lead = procesar_elemento_osm(el, rubro_es, 'COMERCIO')
        if not vistos.dup(lead):
            candidatos.append(lead)
            
    random.shuffle(candidatos)
    elegidos = candidatos[:TOTAL_COMERCIOS]
    
    for l in elegidos:
        vistos.add(l)
        
    print('Comercios reales obtenidos del mapa público: %d' % len(elegidos))
    return elegidos


def buscar_instituciones(vistos):
    query = f"""[out:json][timeout:30];
    (
      node["office"="association"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
      node["office"="government"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
      node["office"="company"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
    );
    out body;"""
    
    elementos = consultar_mapa(query)
    candidatos = []
    
    for el in elementos:
        tags = el.get('tags', {})
        nombre = tags.get('name', '')
        if not nombre:
            continue
            
        lead = procesar_elemento_osm(el, 'Institución', 'GENERADORES')
        if not vistos.dup(lead):
            candidatos.append(lead)
            
    def prioridad(l):
        n = norm(l['nombre'])
        return 0 if any(w in n for w in PALABRAS_INSTITUCION) else 1

    candidatos.sort(key=prioridad)
    elegidos = candidatos[:TOTAL_INSTITUCIONES]
    
    for l in elegidos:
        vistos.add(l)
        
    print('Instituciones reales obtenidas del mapa público: %d' % len(elegidos))
    return elegidos


# ---------- Odoo ----------
class Odoo:
    def __init__(self):
        self.uid = self.rpc('common', 'authenticate', [ODOO_DB, ODOO_USER, ODOO_KEY, {}])
        if not self.uid:
            raise RuntimeError('Odoo rechazó el acceso. Revisá ODOO_DB, ODOO_USER y ODOO_KEY.')

    def rpc(self, service, method, args):
        cuerpo = {'jsonrpc': '2.0', 'method': 'call', 'params': {'service': service, 'method': method, 'args': args}, 'id': 1}
        req = urllib.request.Request(ODOO_URL + '/jsonrpc', data=json.dumps(cuerpo).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode('utf-8'))
        if res.get('error'):
            raise RuntimeError('Error de Odoo: ' + str((res['error'].get('data') or {}).get('message') or res['error'].get('message')))
        return res.get('result')

    def ejecutar(self, modelo, metodo, args, kwargs=None):
        return self.rpc('object', 'execute_kw', [ODOO_DB, self.uid, ODOO_KEY, modelo, metodo, args, kwargs or {}])

    def etapa_id(self):
        r = self.ejecutar('crm.stage', 'search_read', [[['name', '=', ODOO_ETAPA]]], {'fields': ['id'], 'limit': 1})
        if not r:
            todas = self.ejecutar('crm.stage', 'search_read', [[]], {'fields': ['name']})
            raise RuntimeError('No existe la etapa «%s». Las etapas que hay son: %s' % (ODOO_ETAPA, ', '.join(x['name'] for x in todas)))
        return r[0]['id']

    def tag_id(self, nombre):
        r = self.ejecutar('crm.tag', 'search_read', [[['name', '=', nombre]]], {'fields': ['id'], 'limit': 1})
        if r:
            return r[0]['id']
        return self.ejecutar('crm.tag', 'create', [{'name': nombre}])

    def cargar_vistos(self, vistos):
        offset = 0
        while True:
            filas = self.ejecutar('crm.lead', 'search_read', [[]], {
                'fields': ['name', 'street', 'phone', 'email_from'], 'limit': 2000, 'offset': offset,
                'context': {'active_test': False}})
            for f in filas:
                vistos.add({'nombre': f.get('name'), 'direccion': f.get('street'),
                            'telefono': f.get('phone'), 'email': f.get('email_from')})
            if len(filas) < 2000:
                break
            offset += 2000
        print('Leads que ya existen en Odoo: %d' % len(vistos.claves))

    def crear_lead(self, l, stage, tag):
        vals = {
            'name': l['nombre'],
            'partner_name': l['nombre'],
            'phone': l.get('telefono') or False,
            'email_from': l.get('email') or False,
            'street': l.get('direccion') or False,
            'stage_id': stage,
            'tag_ids': [[6, 0, [tag]]],
            'type': 'opportunity',
            'description': 'Rubro: ' + (l.get('rubro') or '') + ' | Info de origen: Datos geográficos reales de OpenStreetMap.',
        }
        return self.ejecutar('crm.lead', 'create', [vals])


def main():
    vistos = Vistos()
    odoo = None
    if ODOO_URL and ODOO_DB and ODOO_USER and ODOO_KEY:
        odoo = Odoo()
        odoo.cargar_vistos(vistos)
    elif not DRY_RUN:
        sys.exit('Faltan secretos de Odoo (ODOO_URL, ODOO_DB, ODOO_USER, ODOO_KEY, ODOO_ETAPA).')
    else:
        print('AVISO: sin datos de Odoo, no se puede evitar repetir leads ya cargados.')

    leads = buscar_comercios(vistos) + buscar_instituciones(vistos)
    print('Total de leads armados: %d' % len(leads))

    cargados, errores = 0, 0
    if DRY_RUN:
        print('PRUEBA: no se carga nada en Odoo. Estos son los leads:')
        for l in leads:
            print('- [%s] %s | %s | %s | %s' % (l['etiqueta'], l['nombre'], l.get('telefono') or '-', l.get('email') or '-', l['direccion']))
    else:
        stage = odoo.etapa_id()
        tags = {'COMERCIO': odoo.tag_id('COMERCIO'), 'GENERADORES': odoo.tag_id('GENERADORES')}
        for l in leads:
            try:
                odoo.crear_lead(l, stage, tags[l['etiqueta']])
                cargados += 1
            except Exception as e:
                errores += 1
                print('ERROR al cargar %s: %s' % (l['nombre'], e))

    resumen = 'Leads armados: %d | cargados en Odoo: %d | errores: %d | modo prueba: %s' % (len(leads), cargados, errores, 'sí' if DRY_RUN else 'no')
    print(resumen)
    ruta = os.environ.get('GITHUB_STEP_SUMMARY')
    if ruta:
        with open(ruta, 'a', encoding='utf-8') as f:
            f.write('### Resultado' + chr(10) + resumen + chr(10))
    if not DRY_RUN and cargados == 0:
        sys.exit('No se cargó ningún lead.')


if __name__ == '__main__':
    main()
