import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xmlrpc.client

# Configuración de credenciales de Odoo (Variables de entorno)
ODOO_URL = os.environ.get('ODOO_URL', '').strip().rstrip('/')
ODOO_DB = os.environ.get('ODOO_DB', '').strip()
ODOO_USER = os.environ.get('ODOO_USER', '').strip()
ODOO_KEY = os.environ.get('ODOO_KEY', '').strip()
ODOO_ETAPA = os.environ.get('ODOO_ETAPA', '').strip() # ID de etapa de CRM o flujo
ODOO_EMPRESA = os.environ.get('ODOO_EMPRESA', '').strip() # ID de tu empresa en Odoo
DRY_RUN = os.environ.get('DRY_RUN', '0') == '1'

# Configuración geográfica de búsqueda (Córdoba, Argentina)
LAT_MIN, LON_MIN, LAT_MAX, LON_MAX = -31.4700, -64.2500, -31.3500, -64.1200

# Mapeo de rubros para OpenStreetMap
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

def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub('[ ]+', ' ', s.lower().strip())

def obtener_datos_osm():
    """Consulta la API pública y gratuita de Overpass para traer comercios reales"""
    url = "https://overpass-api.de"
    
    condiciones = ""
    for rubro_osm in RUBROS_OSM.values():
        condiciones += f'  node["shop"="{rubro_osm}"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});\n'
        condiciones += f'  node["amenity"="{rubro_osm}"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});\n'
    
    query = f"""
    [out:json][timeout:30];
    (
    {condiciones}
    );
    out body;
    """
    
    data = urllib.parse.urlencode({'data': query}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'User-Agent': 'ExtractorLeadsOdoo/2.0'})
    
    try:
        with urllib.request.urlopen(req) as response:
            resultado = json.loads(response.read().decode('utf-8'))
            return resultado.get('elements', [])
    except Exception as e:
        print(f"Error al obtener datos públicos: {e}")
        return []

def subir_a_odoo(leads):
    """Conecta con Odoo vía XML-RPC e inserta los leads reales"""
    if not all([ODOO_URL, ODOO_DB, ODOO_USER, ODOO_KEY]):
        print("Faltan configurar variables de entorno de Odoo. Abortando subida.")
        return

    print(f"Conectando a Odoo en {ODOO_URL}...")
    try:
        common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
        uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_KEY, {})
        if not uid:
            print("Error de autenticación en Odoo. Verificá usuario y contraseña/API Key.")
            return
        
        models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')
    except Exception as e:
        print(f"Error en la conexión XML-RPC con Odoo: {e}")
        return

    for lead in leads:
        # Mapeo de campos para Odoo (modelo res.partner o crm.lead según necesites)
        # En este caso se asume la creación de Iniciativas/Oportunidades (crm.lead)
        payload = {
            'name': f"{lead['nombre']} - {lead['rubro']}",
            'partner_name': lead['nombre'],
            'street': lead['direccion'],
            'city': 'Córdoba',
            'phone': lead['telefono'],
            'description': f"Coordenadas geográficas reales: {lead['coordenadas']}",
        }
        
        # Asignar Etapa y Empresa si están definidas en tus variables de entorno
        if ODOO_ETAPA:
            payload['stage_id'] = int(ODOO_ETAPA)
        if ODOO_EMPRESA:
            payload['company_id'] = int(ODOO_EMPRESA)

        if DRY_RUN:
            print(f"[DRY_RUN] Se crearía en Odoo: {payload['name']} | Tel: {payload['phone']}")
        else:
            try:
                lead_id = models.execute_kw(ODOO_DB, uid, ODOO_KEY, 'crm.lead', 'create', [payload])
                print(f"Lead creado exitosamente en Odoo con ID: {lead_id}")
                time.sleep(0.5) # Pausa leve para evitar saturar el servidor
            except Exception as e:
                print(f"Error al insertar el lead {lead['nombre']} en Odoo: {e}")

def procesar_leads():
    elementos = obtener_datos_osm()
    if not elementos:
        print("No se recuperaron comercios del mapa.")
        return

    leads_reales = []
    for el in elementos:
        tags = el.get('tags', {})
        nombre = tags.get('name')
        
        if not nombre:
            continue
            
        calle = tags.get('addr:street', '')
        altura = tags.get('addr:housenumber', '')
        direccion = f"{calle} {altura}".strip() if calle else "Dirección no especificada"
        
        # Extrae el teléfono si está cargado por el dueño del local en el mapa
        telefono = tags.get('phone', tags.get('contact:phone', 'Sin teléfono registrado'))
        
        tipo_comercio = tags.get('shop', tags.get('amenity', 'Otros'))
        rubro_es = next((k for k, v in RUBROS_OSM.items() if v == tipo_comercio), 'Comercio')

        leads_reales.append({
            'nombre': nombre,
            'rubro': rubro_es,
            'direccion': direccion,
            'telefono': telefono,
            'coordenadas': f"{el.get('lat')}, {el.get('lon')}"
        })

    print(f"Se procesaron {len(leads_reales)} comercios reales listos para procesar.")
    subir_a_odoo(leads_reales)

if __name__ == "__main__":
    procesar_leads()
