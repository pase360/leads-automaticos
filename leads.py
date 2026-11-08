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
 
GEOAPIFY_KEY = os.environ.get('GEOAPIFY_KEY', '').strip()
ODOO_URL = os.environ.get('ODOO_URL', '').strip().rstrip('/')
ODOO_DB = os.environ.get('ODOO_DB', '').strip()
ODOO_USER = os.environ.get('ODOO_USER', '').strip()
ODOO_KEY = os.environ.get('ODOO_KEY', '').strip()
ODOO_ETAPA = os.environ.get('ODOO_ETAPA', '').strip()
ODOO_EMPRESA = os.environ.get('ODOO_EMPRESA', '').strip()
DRY_RUN = os.environ.get('DRY_RUN', '0') == '1'
 
CIUDAD = 'Córdoba, Argentina'
CENTRO = (-31.4201, -64.1888)
CARACTERISTICA = '351'
TOTAL_COMERCIOS = 45
TOTAL_INSTITUCIONES = 5
MAX_COMBOS = 120
 
BARRIOS = ['Alberdi', 'Nueva Córdoba', 'Centro', 'General Paz', 'Güemes', 'Cofico',
           'San Vicente', 'Alta Córdoba', 'Observatorio', 'Cerro de las Rosas',
           'Villa Cabrera', 'Jardín', 'Urca', 'Pueyrredón', 'Alto Alberdi', 'Providencia']
 
RUBROS = [
    ['Carnicería', 'commercial.food_and_drink.butcher'],
    ['Panadería', 'commercial.food_and_drink.bakery'],
    ['Zapatería', 'commercial.clothing.shoes'],
    ['Peluquería', 'service.beauty.hairdresser'],
    ['Ropa', 'commercial.clothing.clothes'],
    ['Supermercado', 'commercial.supermarket'],
    ['Café', 'catering.cafe'],
    ['Restaurante', 'catering.restaurant'],
    ['Gimnasio', 'sport.fitness.fitness_centre'],
    ['Farmacia', 'healthcare.pharmacy'],
    ['Florería', 'commercial.florist'],
    ['Óptica', 'commercial.health_and_beauty.optician'],
]
 
PALABRAS_INSTITUCION = ['sindicato', 'asociacion', 'colegio', 'camara', 'federacion',
                        'mutual', 'cooperativa', 'universidad', 'club', 'gremio', 'union']
 
def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub('[ ]+', ' ', s.lower().strip())
 
def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(600000)
        charset = r.headers.get_content_charset() or 'utf-8'
    return data.decode(charset, errors='ignore')
 
def geo(path, params):
    p = dict(params)
    p['apiKey'] = GEOAPIFY_KEY
    url = 'https://api.geoapify.com' + path + '?' + urllib.parse.urlencode(p, quote_via=urllib.parse.quote, safe=',:')
    for intento in range(3):
        try:
            time.sleep(0.25)
            return json.loads(http_get(url, 20))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (intento + 1))
                continue
            return {'_error': e.code}
        except Exception:
            time.sleep(1)
    return {'_error': 0}
 
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
 
def sacar(pr, claves):
    c = pr.get('contact') or {}
    raw = (pr.get('datasource') or {}).get('raw') or {}
    for k in claves:
        v = c.get(k) or raw.get(k) or pr.get(k)
        if v:
            return str(v)
    return ''
 
def clasificar(datos, rubro, barrio, etiqueta):
    con, sin = [], []
    for f in (datos.get('features') or []):
        pr = f.get('properties') or {}
        nombre = pr.get('name')
        if not nombre:
            continue
        l = {
            'nombre': nombre,
            'telefono': sacar(pr, ['phone', 'mobile', 'contact:phone', 'contact:mobile']),
            'email': sacar(pr, ['email', 'contact:email']),
            'direccion': pr.get('formatted') or pr.get('address_line2') or '',
            'rubro': rubro,
            'barrio': barrio,
            'etiqueta': etiqueta,
            'web': sacar(pr, ['website', 'contact:website']),
        }
        (con if (l['telefono'] or l['email']) else sin).append(l)
    return con, sin
 
_coords = {}
 
def coordenadas(barrio):
    if barrio not in _coords:
        d = geo('/v1/geocode/search', {'text': barrio + ', ' + CIUDAD, 'limit': 1, 'format': 'json'})
        res = d.get('results') or []
        _coords[barrio] = (res[0].get('lat'), res[0].get('lon')) if res else CENTRO
    return _coords[barrio]
 
def extraer_contacto(html, nombre, tiene_web):
    html = (html or '')[:400000]
    if not tiene_web:
        i = html.lower().find((nombre or '').lower()[:12])
        if i < 0:
            return '', ''
        html = html[max(0, i - 1500): i + 1500]
    tel = ''
    for patron in [r'wa[.]me/([+]?[0-9]{10,13})', r'api[.]whatsapp[.]com/send[?]phone=([0-9]{10,13})',
                   r'href=.tel:([+0-9 ()-]{8,20})']:
        m = re.search(patron, html)
        if m:
            tel = m.group(1)
            break
    if not tel:
        m = re.search(r'(?:[+]?54[ ]?9?[ ]?)?[(]?0?' + CARACTERISTICA + r'[)]?[ -]?(?:15)?[ -]?[0-9]{3}[ -]?[0-9]{4}', html)
        if m:
            tel = m.group(0)
    mail = ''
    for e in re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}', html):
        el = e.lower()
        if el.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.js', '.css')):
            continue
        if any(x in el for x in ['sentry', 'wixpress', 'example', 'duckduckgo', 'schema.org']):
            continue
        mail = e
        break
    return tel, mail
 
def rescatar(pendientes, faltan, vistos):
    cand = [p for p in pendientes if not vistos.dup(p)]
    random.shuffle(cand)
    cand.sort(key=lambda l: 0 if l['web'] else 1)
    logrados = []
    for p in cand[:min(60, faltan * 3)]:
        if len(logrados) >= faltan:
            break
        try:
            if p['web']:
                url = p['web'] if p['web'].startswith('http') else 'http://' + p['web']
                html = http_get(url, 10)
            else:
                q = p['nombre'] + ' ' + p['barrio'] + ' ' + CIUDAD.split(',')[0] + ' teléfono'
                html = http_get('https://html.duckduckgo.com/html/?q=' + urllib.parse.quote(q), 10)
        except Exception:
            continue
        tel, mail = extraer_contacto(html, p['nombre'], bool(p['web']))
        if tel or mail:
            p['telefono'], p['email'] = tel, mail
            if not vistos.dup(p):
                vistos.add(p)
                logrados.append(p)
        time.sleep(1)
    return logrados
 
def buscar_comercios(vistos):
    combos = [(b, r) for b in BARRIOS for r in RUBROS]
    random.shuffle(combos)
    malas = set()
    por_combo = []
    pendientes = []
    for b, r in combos[:MAX_COMBOS]:
        if r[1] in malas:
            continue
        lat, lon = coordenadas(b)
        d = geo('/v2/places', {'categories': r[1], 'filter': 'circle:%s,%s,1500' % (lon, lat), 'limit': 20})
        if d.get('_error'):
            if d['_error'] == 400:
                malas.add(r[1])
                print('AVISO: la categoría %s no es válida en Geoapify, se saltea.' % r[1])
            continue
        con, sin = clasificar(d, r[0], b, 'COMERCIO')
        con = [l for l in con if not vistos.dup(l)]
        if con:
            random.shuffle(con)
            por_combo.append(con)
        pendientes.extend(sin)
        if len(por_combo) >= int(TOTAL_COMERCIOS * 1.2):
            break
    elegidos = []
    for ronda in range(6):
        for lista in por_combo:
            if len(elegidos) >= TOTAL_COMERCIOS:
                break
            if len(lista) > ronda and not vistos.dup(lista[ronda]):
                vistos.add(lista[ronda])
                elegidos.append(lista[ronda])
    print('Comercios con contacto directo de Geoapify: %d' % len(elegidos))
    if len(elegidos) < TOTAL_COMERCIOS:
        rescatados = rescatar(pendientes, TOTAL_COMERCIOS - len(elegidos), vistos)
        print('Comercios rescatados leyendo webs o buscando en internet: %d' % len(rescatados))
        elegidos.extend(rescatados)
    return elegidos
 
def buscar_instituciones(vistos):
    base = {'categories': 'office.association,office.company',
            'filter': 'circle:%s,%s,10000' % (CENTRO[1], CENTRO[0]), 'limit': 50}
    con, sin = [], []
    for offset in [random.randint(0, 6) * 50, 0]:
        p = dict(base)
        p['offset'] = offset
        d = geo('/v2/places', p)
        if d.get('_error'):
            continue
        con, sin = clasificar(d, 'Institución', CIUDAD.split(',')[0], 'GENERADORES')
        if con or sin:
            break
 
    def prioridad(l):
        n = norm(l['nombre'])
        return 0 if any(w in n for w in PALABRAS_INSTITUCION) else 1
 
    random.shuffle(con)
    con = [l for l in con if not vistos.dup(l)]
    con.sort(key=prioridad)
    elegidos = []
    for l in con:
        if len(elegidos) >= TOTAL_INSTITUCIONES:
            break
        if not vistos.dup(l):
            vistos.add(l)
            elegidos.append(l)
    if len(elegidos) < TOTAL_INSTITUCIONES:
        sin.sort(key=prioridad)
        elegidos.extend(rescatar(sin, TOTAL_INSTITUCIONES - len(elegidos), vistos))
    print('Instituciones: %d' % len(elegidos))
    return elegidos
 
class Odoo:
    def __init__(self):
        self.uid = self.rpc('common', 'authenticate', [ODOO_DB, ODOO_USER, ODOO_KEY, {}])
        if not self.uid:
            raise RuntimeError('Odoo rechazó el acceso. Revisá ODOO_DB, ODOO_USER y ODOO_KEY.')
        self.company = None
        self.ctx = {}
        if ODOO_EMPRESA:
            r = self.ejecutar('res.company', 'search_read', [[['name', '=', ODOO_EMPRESA]]], {'fields': ['id'], 'limit': 1})
            if not r:
                todas = self.ejecutar('res.company', 'search_read', [[]], {'fields': ['name']})
                raise RuntimeError('No existe la empresa «%s». Las empresas a las que tiene acceso el usuario son: %s' % (ODOO_EMPRESA, ', '.join(x['name'] for x in todas)))
            self.company = r[0]['id']
            self.ctx = {'allowed_company_ids': [self.company]}
            print('Empresa de Odoo: %s' % ODOO_EMPRESA)
 
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
        kw = dict(kwargs or {})
        if self.ctx and modelo != 'res.company':
            ctx = dict(kw.get('context') or {})
            ctx.update(self.ctx)
            kw['context'] = ctx
        return self.rpc('object', 'execute_kw', [ODOO_DB, self.uid, ODOO_KEY, modelo, metodo, args, kw])
 
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
            dominio = [['company_id', '=', self.company]] if self.company else []
            filas = self.ejecutar('crm.lead', 'search_read', [dominio], {
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
            'description': 'Rubro: ' + (l.get('rubro') or '') + ' | Barrio: ' + (l.get('barrio') or ''),
        }
        if self.company:
            vals['company_id'] = self.company
        return self.ejecutar('crm.lead', 'create', [vals])
 
def main():
    if not GEOAPIFY_KEY:
        sys.exit('Falta el secreto GEOAPIFY_KEY.')
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
            print('- [%s] %s | %s | %s | %s | %s' % (l['etiqueta'], l['nombre'], l.get('telefono') or '-', l.get('email') or '-', l['barrio'], l['direccion']))
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
 
