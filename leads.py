import json
import os
import random
import re
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SERPER_KEY = os.environ.get('SERPER_KEY', '').strip()
ODOO_URL = os.environ.get('ODOO_URL', '').strip().rstrip('/')
ODOO_DB = os.environ.get('ODOO_DB', '').strip()
ODOO_USER = os.environ.get('ODOO_USER', '').strip()
ODOO_KEY = os.environ.get('ODOO_KEY', '').strip()
ODOO_ETAPA = os.environ.get('ODOO_ETAPA', '').strip()
ODOO_EMPRESA = os.environ.get('ODOO_EMPRESA', '').strip()
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
DRY_RUN = os.environ.get('DRY_RUN', '0') == '1'

CIUDAD = 'Córdoba, Argentina'
CARACTERISTICA = '351'
PREFIJOS_CELULAR = '678'
TOTAL_COMERCIOS = 45
TOTAL_INSTITUCIONES = 5
MAX_BUSQUEDAS_COMERCIOS = 24
MAX_BUSQUEDAS_INSTITUCIONES = 8
POR_BUSQUEDA = 4
HISTORIAL = 'historial.txt'

BARRIOS = [
    'Alberdi', 'Alto Alberdi', 'Alta Córdoba', 'Alto Verde', 'Altamira', 'Argüello', 'Ayacucho',
    'Bajo General Paz', 'Bajo Palermo', 'Bajo Pueyrredón', 'Balcarce', 'Cañada', 'Centro',
    'Cerro de las Rosas', 'Cerveceros', 'Chateau Carreras', 'Cofico', 'Colinas de Vélez Sarsfield',
    'Crisol Norte', 'Crisol Sur', 'Dean Funes', 'Ejército Argentino', 'Empalme', 'Escobar',
    'Ferreyra', 'General Bustos', 'General Mitre', 'General Paz', 'Guiñazú', 'Güemes', 'Inaudi',
    'Jardín', 'Jardín Espinosa', 'Juniors', 'Las Palmas', 'Las Rosas', 'Los Boulevares',
    'Los Naranjos', 'Los Paraísos', 'Los Plátanos', 'Maipú', 'Marqués de Sobremonte', 'Matienzo',
    'Mariano Fragueiro', 'Müller', 'Nueva Córdoba', 'Observatorio', 'Parque Capital',
    'Parque Vélez Sarsfield', 'Poeta Lugones', 'Providencia', 'Pueblo Nuevo', 'Pueyrredón',
    'Residencial América', 'Rogelio Martínez', 'San Fernando', 'San Martín', 'San Vicente',
    'Santa Isabel', 'Talleres', 'Urca', 'Villa Belgrano', 'Villa Cabrera', 'Villa El Libertador',
    'Villa Páez', 'Villa Revol', 'Villa Rivera Indarte', 'Villa Siburu', 'Villa Warcalde',
    'Yofre Norte', 'Yofre Sur', 'Zumarán',
]

RUBROS = [
    'carnicería', 'panadería', 'zapatería', 'peluquería', 'tienda de ropa', 'supermercado',
    'café', 'restaurante', 'gimnasio', 'farmacia', 'florería', 'óptica', 'ferretería',
    'librería', 'kiosco', 'verdulería', 'lavadero de autos', 'veterinaria', 'pastelería',
    'heladería', 'centro de estética', 'joyería', 'juguetería', 'mueblería', 'taller mecánico',
    'perfumería', 'pinturería', 'bazar', 'rotisería', 'dietética',
]

INSTITUCIONES = [
    'sindicato', 'asociación de profesionales', 'colegio de profesionales', 'cámara empresarial',
    'mutual', 'cooperativa', 'federación', 'gremio', 'clínica privada', 'call center',
    'concesionaria', 'club social', 'universidad privada',
]

PALABRAS_MAIL = ['ventas', 'comercial', 'administracion', 'admin', 'gerencia', 'contacto',
                 'info', 'consultas', 'hola']
COMILLAS = chr(34) + chr(39)


def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub('[ ]+', ' ', s.lower().strip())


BARRIOS_NORM = set(norm(b) for b in BARRIOS)


def http_get(url, timeout=15, inseguro=False):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    ctx = ssl._create_unverified_context() if inseguro else None
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        data = r.read(600000)
        charset = r.headers.get_content_charset() or 'utf-8'
    return data.decode(charset, errors='ignore')


def http_leer(url):
    try:
        return http_get(url, 8, True)
    except Exception:
        return ''


class Vistos:
    def __init__(self):
        self.items = set()

    @staticmethod
    def entradas(l):
        e = ['k:' + norm(l.get('nombre')) + '|' + norm(l.get('direccion'))]
        d = re.sub('[^0-9]', '', l.get('telefono') or '')
        if len(d) >= 8:
            e.append('t:' + d[-8:])
        m = (l.get('email') or '').lower()
        if m:
            e.append('m:' + m)
        return e

    def dup(self, l):
        return any(x in self.items for x in self.entradas(l))

    def add(self, l):
        self.items.update(self.entradas(l))


def cargar_historial(vistos):
    if not os.path.exists(HISTORIAL):
        return
    with open(HISTORIAL, encoding='utf-8') as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                vistos.items.add(linea)
    print('Leads en el historial del repositorio: %d' % len(vistos.items))


def guardar_historial(leads):
    with open(HISTORIAL, 'a', encoding='utf-8') as f:
        for l in leads:
            for e in Vistos.entradas(l):
                f.write(e + chr(10))


def normalizar_celular(raw, seguro=False):
    d = re.sub('[^0-9]', '', raw or '')
    if d.startswith('54'):
        d = d[2:]
        if d.startswith('9'):
            d = d[1:]
            seguro = True
    if d.startswith('0'):
        d = d[1:]
    if len(d) == 12:
        for a in (2, 3, 4):
            if d[a:a + 2] == '15':
                d = d[:a] + d[a + 2:]
                seguro = True
                break
    if len(d) != 10:
        return None
    if not seguro:
        if not (d.startswith(CARACTERISTICA) and d[len(CARACTERISTICA)] in PREFIJOS_CELULAR):
            return None
    return ('+549' + d, seguro)


def puntaje_mail(m):
    local = m.lower().split('@')[0]
    for i, w in enumerate(PALABRAS_MAIL):
        if w in local:
            return i
    return 50


def mail_valido(e):
    el = e.lower()
    if el.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.js', '.css', '.woff', '.ico')):
        return False
    malos = ['sentry', 'wixpress', 'example', 'schema.org', 'noreply', 'no-reply', 'donotreply',
             'webmaster', 'postmaster', 'duckduckgo', 'domain.com', 'tuemail', 'email@']
    return not any(x in el for x in malos)


P_WA = [r'wa[.]me/([+]?[0-9]{10,14})', r'api[.]whatsapp[.]com/send[?]phone=([0-9]{10,14})',
        r'web[.]whatsapp[.]com/send[?]phone=([0-9]{10,14})', r'whatsapp://send[?]phone=([0-9]{10,14})']
P_TEL = r'href=.tel:([+0-9 ()-]{8,25})'
P_INT = r'(?<![0-9])[+]54[ -]?9[ -]?[0-9]{2,4}[ -]?[0-9]{3,4}[ -]?[0-9]{3,4}(?![0-9])'
P_15 = r'(?<![0-9])0?[0-9]{2,4}[ -]?[(]?15[)]?[ -]?[0-9]{3,4}[ -]?[0-9]{3,4}(?![0-9])'
P_LOCAL = r'(?<![0-9])(?:[+]54[ -]?)?0?' + CARACTERISTICA + r'[ -]?[0-9]{3}[ -]?[0-9]{4}(?![0-9])'
P_MAIL = r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}'


def extraer(html):
    html = html or ''
    nums = []
    for patron in P_WA:
        for m in re.findall(patron, html):
            n = normalizar_celular(m, True)
            if n:
                nums.append(n)
    for m in re.findall(P_TEL, html):
        n = normalizar_celular(m, False)
        if n:
            nums.append(n)
    for patron in [P_INT, P_15, P_LOCAL]:
        for m in re.findall(patron, html):
            n = normalizar_celular(m, False)
            if n:
                nums.append(n)
    mails = [e for e in re.findall(P_MAIL, html) if mail_valido(e)]
    return nums, mails


def leer_sitio(web):
    if not web.startswith('http'):
        web = 'http://' + web
    base = http_leer(web)
    textos = [base]
    host = urllib.parse.urlparse(web).netloc
    enlaces = []
    for h in re.findall(r'href=.([^ >]+)', base):
        h = h.strip(COMILLAS)
        if h.lower().startswith(('mailto', 'tel', 'javascript', '#')):
            continue
        if any(w in h.lower() for w in ['contact', 'nosotros']):
            u = urllib.parse.urljoin(web, h)
            if urllib.parse.urlparse(u).netloc == host and u != web and u not in enlaces:
                enlaces.append(u)
    for u in enlaces[:2]:
        textos.append(http_leer(u))
    return ' '.join(textos)


def enriquecer(l):
    try:
        cands = []
        n = normalizar_celular(l.get('maps_tel'), False)
        if n:
            cands.append(n)
        mails = []
        if l.get('web'):
            c2, m2 = extraer(leer_sitio(l['web']))
            cands.extend(c2)
            mails.extend(m2)
        cands.sort(key=lambda x: 0 if x[1] else 1)
        mails = sorted(dict.fromkeys(mails), key=puntaje_mail)
        cel = cands[0] if cands else ('', False)
        return (cel[0], cel[1], mails[0] if mails else '')
    except Exception:
        return ('', False, '')


gastadas = [0]


def serper_maps(q):
    cuerpo = json.dumps({'q': q, 'gl': 'ar', 'hl': 'es'}).encode('utf-8')
    for intento in range(3):
        req = urllib.request.Request('https://google.serper.dev/maps', data=cuerpo,
                                     headers={'X-API-KEY': SERPER_KEY, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                gastadas[0] += 1
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (intento + 1))
                continue
            raise RuntimeError('Serper rechazó la búsqueda (código %s). Revisá SERPER_KEY o si se acabaron los créditos.' % e.code)
        except Exception:
            time.sleep(2)
    raise RuntimeError('No se pudo conectar con Serper.')


def nombre_invalido(n):
    x = norm(n).replace('barrio ', '')
    return len(x) < 3 or x in BARRIOS_NORM or x in ('cordoba', 'cordoba capital', 'argentina')


def procesar(lugares, rubro, barrio, etiqueta, vistos, maximo):
    cand = []
    for p in lugares:
        nombre = (p.get('title') or p.get('name') or '').strip()
        if not nombre or nombre_invalido(nombre):
            continue
        l = {
            'nombre': nombre,
            'direccion': (p.get('address') or '').strip(),
            'web': (p.get('website') or '').strip(),
            'maps_tel': p.get('phoneNumber') or p.get('phone') or '',
            'rubro': rubro,
            'barrio': barrio,
            'etiqueta': etiqueta,
        }
        if vistos.dup(l):
            continue
        cand.append(l)
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(enriquecer, cand))
    buenos = []
    for l, (tel, conf, mail) in zip(cand, res):
        if not tel and not mail:
            continue
        l['telefono'] = tel
        l['tel_confirmado'] = conf
        l['email'] = mail
        buenos.append(l)
    buenos.sort(key=lambda l: (0 if (l['telefono'] and l['email']) else (1 if l['telefono'] else 2)))
    elegidos = []
    for l in buenos:
        if len(elegidos) >= maximo:
            break
        if not vistos.dup(l):
            vistos.add(l)
            elegidos.append(l)
    return elegidos


def buscar_comercios(vistos):
    combos = [(b, r) for b in BARRIOS for r in RUBROS]
    random.shuffle(combos)
    elegidos = []
    for b, r in combos[:MAX_BUSQUEDAS_COMERCIOS]:
        if len(elegidos) >= TOTAL_COMERCIOS:
            break
        d = serper_maps('%s en %s, %s' % (r, b, CIUDAD))
        nuevos = procesar(d.get('places') or [], r, b, 'COMERCIO', vistos, POR_BUSQUEDA)
        elegidos.extend(nuevos)
        print('%s en %s: %d leads con celular o mail' % (r, b, len(nuevos)))
    return elegidos[:TOTAL_COMERCIOS]


def buscar_instituciones(vistos):
    tipos = list(INSTITUCIONES)
    random.shuffle(tipos)
    elegidos = []
    for t in tipos[:MAX_BUSQUEDAS_INSTITUCIONES]:
        if len(elegidos) >= TOTAL_INSTITUCIONES:
            break
        d = serper_maps('%s en %s' % (t, CIUDAD))
        nuevos = procesar(d.get('places') or [], 'Institución: ' + t, CIUDAD.split(',')[0], 'GENERADORES', vistos, 2)
        elegidos.extend(nuevos)
        print('%s: %d leads con celular o mail' % (t, len(nuevos)))
    return elegidos[:TOTAL_INSTITUCIONES]


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
        print('Leads que ya existen en Odoo: %d' % len(vistos.items))

    def crear_lead(self, l, stage, tag):
        nota = 'Fuente: Google Maps | Rubro: %s | Búsqueda en: %s' % (l.get('rubro') or '', l.get('barrio') or '')
        if l.get('telefono'):
            nota += ' | Celular ' + ('confirmado por WhatsApp o formato celular' if l.get('tel_confirmado') else 'probable')
        vals = {
            'name': l['nombre'],
            'partner_name': l['nombre'],
            'phone': l.get('telefono') or False,
            'email_from': l.get('email') or False,
            'street': l.get('direccion') or False,
            'website': l.get('web') or False,
            'stage_id': stage,
            'tag_ids': [[6, 0, [tag]]],
            'type': 'opportunity',
            'description': nota,
        }
        if self.company:
            vals['company_id'] = self.company
        return self.ejecutar('crm.lead', 'create', [vals])


def avisar(texto):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        datos = urllib.parse.urlencode({'chat_id': TELEGRAM_CHAT_ID, 'text': texto}).encode('utf-8')
        req = urllib.request.Request('https://api.telegram.org/bot' + TELEGRAM_TOKEN + '/sendMessage', data=datos)
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        print('No se pudo enviar el aviso de Telegram: %s' % e)


def principal():
    if not SERPER_KEY:
        sys.exit('Falta el secreto SERPER_KEY.')
    vistos = Vistos()
    cargar_historial(vistos)
    odoo = None
    if ODOO_URL and ODOO_DB and ODOO_USER and ODOO_KEY:
        odoo = Odoo()
        odoo.cargar_vistos(vistos)
    elif not DRY_RUN:
        sys.exit('Faltan secretos de Odoo (ODOO_URL, ODOO_DB, ODOO_USER, ODOO_KEY, ODOO_ETAPA).')
    else:
        print('AVISO: sin datos de Odoo, no se puede evitar repetir leads ya cargados en Odoo.')

    comercios = buscar_comercios(vistos)
    instituciones = buscar_instituciones(vistos)
    leads = comercios + instituciones
    print('Armados: %d comercios y %d instituciones' % (len(comercios), len(instituciones)))

    cargados = []
    errores = 0
    if DRY_RUN:
        print('PRUEBA: no se carga nada en Odoo. Estos son los leads:')
        for l in leads:
            print('- [%s] %s | cel: %s | mail: %s | %s' % (l['etiqueta'], l['nombre'], l.get('telefono') or '-', l.get('email') or '-', l['direccion']))
    else:
        stage = odoo.etapa_id()
        tags = {'COMERCIO': odoo.tag_id('COMERCIO'), 'GENERADORES': odoo.tag_id('GENERADORES')}
        for l in leads:
            try:
                odoo.crear_lead(l, stage, tags[l['etiqueta']])
                cargados.append(l)
            except Exception as e:
                errores += 1
                print('ERROR al cargar %s: %s' % (l['nombre'], e))
        if cargados:
            guardar_historial(cargados)

    con_cel = len([l for l in leads if l.get('telefono')])
    con_mail = len([l for l in leads if l.get('email')])
    resumen = 'Leads: %d armados (%d comercios, %d instituciones), %d con celular, %d con mail, %d cargados en Odoo, %d errores, %d búsquedas de Serper usadas.' % (
        len(leads), len(comercios), len(instituciones), con_cel, con_mail, len(cargados), errores, gastadas[0])
    if DRY_RUN:
        resumen += ' (modo prueba)'
    print(resumen)
    ruta = os.environ.get('GITHUB_STEP_SUMMARY')
    if ruta:
        with open(ruta, 'a', encoding='utf-8') as f:
            f.write('### Resultado' + chr(10) + resumen + chr(10))
    if not DRY_RUN:
        avisar(resumen)
        if not cargados:
            sys.exit('No se cargó ningún lead.')


def main():
    try:
        principal()
    except SystemExit as e:
        if e.code not in (None, 0) and not DRY_RUN:
            avisar('Falló la corrida de leads: %s' % e.code)
        raise
    except Exception as e:
        if not DRY_RUN:
            avisar('Falló la corrida de leads: %s' % e)
        raise


if __name__ == '__main__':
    main()
