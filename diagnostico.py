import json
import os
import re
import sys
import urllib.request

URL = os.environ.get('ODOO_URL', '').strip().rstrip('/')
DB = os.environ.get('ODOO_DB', '').strip()
USER = os.environ.get('ODOO_USER', '').strip()
KEY = os.environ.get('ODOO_KEY', '').strip()
EMPRESA = os.environ.get('ODOO_EMPRESA', '').strip()
SENSIBLES = ['token', 'secret', 'password', 'key', 'pass']


def rpc(service, method, args):
    cuerpo = {'jsonrpc': '2.0', 'method': 'call', 'params': {'service': service, 'method': method, 'args': args}, 'id': 1}
    req = urllib.request.Request(URL + '/jsonrpc', data=json.dumps(cuerpo).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.loads(r.read().decode('utf-8'))
    if res.get('error'):
        raise RuntimeError(str((res['error'].get('data') or {}).get('message') or res['error'].get('message')))
    return res.get('result')


def corto(v, n=70):
    if isinstance(v, (list, tuple)) and len(v) == 2 and isinstance(v[0], int):
        v = v[1]
    t = re.sub('<[^>]+>', ' ', str(v))
    t = re.sub('[ ]+', ' ', t).strip()
    return t[:n]


class Diag:
    def __init__(self):
        self.uid = rpc('common', 'authenticate', [DB, USER, KEY, {}])
        if not self.uid:
            sys.exit('Odoo rechazo el acceso. Revisa los secretos de Odoo.')
        self.ctx = {}
        if EMPRESA:
            r = self.ej('res.company', 'search_read', [[['name', '=', EMPRESA]]], {'fields': ['id'], 'limit': 1}, False)
            if r:
                self.ctx = {'allowed_company_ids': [r[0]['id']]}

    def ej(self, modelo, metodo, args, kw=None, ctx=True):
        kw = dict(kw or {})
        if ctx and self.ctx:
            kw['context'] = dict(kw.get('context') or {}, **self.ctx)
        return rpc('object', 'execute_kw', [DB, self.uid, KEY, modelo, metodo, args, kw])

    def campos(self, modelo):
        return self.ej(modelo, 'fields_get', [], {'attributes': ['string', 'type']})

    def volcar(self, titulo, modelo, dominio, candidatos, orden=None, limite=10):
        print('')
        print('=== ' + titulo + ' (' + modelo + ') ===')
        try:
            fg = self.campos(modelo)
        except Exception as e:
            print('No se pudo leer el modelo: ' + str(e)[:150])
            return []
        usar = [c for c in candidatos if c in fg and not any(s in c for s in SENSIBLES)]
        print('Campos leidos: ' + ', '.join(usar))
        kw = {'fields': usar, 'limit': limite}
        if orden:
            kw['order'] = orden
        try:
            filas = self.ej(modelo, 'search_read', [dominio], kw)
        except Exception as e:
            print('No se pudo leer: ' + str(e)[:150])
            return []
        print('Registros: ' + str(len(filas)))
        for f in filas:
            print('- ' + ' | '.join(c + '=' + corto(f.get(c)) for c in usar))
        return filas


def principal():
    d = Diag()
    try:
        v = rpc('common', 'version', [])
        print('Version de Odoo: ' + str(v.get('server_version')))
    except Exception as e:
        print('No se pudo leer la version: ' + str(e)[:100])

    d.volcar('Cuentas de WhatsApp', 'whatsapp.account', [],
             ['name', 'phone_uid', 'account_uid', 'app_uid', 'status', 'active', 'allowed_company_ids'])
    d.volcar('Plantillas de WhatsApp', 'whatsapp.template', [],
             ['name', 'template_name', 'status', 'lang_code', 'quality', 'model', 'wa_account_id', 'template_type'],
             limite=30)
    canales = d.volcar('Conversaciones de WhatsApp', 'discuss.channel', [['channel_type', '=', 'whatsapp']],
                       ['id', 'name', 'channel_type', 'whatsapp_number', 'whatsapp_partner_id', 'wa_account_id',
                        'create_date', 'write_date'], orden='id desc', limite=5)
    ids = [c['id'] for c in canales]
    if ids:
        d.volcar('Ultimos mensajes de esas conversaciones', 'mail.message',
                 [['model', '=', 'discuss.channel'], ['res_id', 'in', ids]],
                 ['id', 'date', 'res_id', 'author_id', 'message_type', 'subtype_id', 'body', 'create_uid'],
                 orden='id desc', limite=12)
    d.volcar('Mensajes de WhatsApp (estado de envio)', 'whatsapp.message', [],
             ['id', 'mobile_number', 'message_type', 'state', 'failure_type', 'failure_reason', 'wa_template_id',
              'create_date', 'mail_message_id'], orden='id desc', limite=12)

    print('')
    print('=== Campos de mensajes que mencionan WhatsApp (mail.message) ===')
    try:
        fg = d.campos('mail.message')
        print(', '.join(sorted(c for c in fg if 'whatsapp' in c or c.startswith('wa_'))) or 'ninguno')
    except Exception as e:
        print('No se pudo leer: ' + str(e)[:100])

    print('')
    print('=== Buscar el lead de cada conversacion por telefono ===')
    for c in canales:
        num = re.sub('[^0-9]', '', str(c.get('whatsapp_number') or ''))
        if len(num) < 8:
            continue
        try:
            leads = d.ej('crm.lead', 'search_read', [[['phone', 'ilike', num[-8:]]]],
                         {'fields': ['id', 'name', 'phone', 'tag_ids', 'stage_id'], 'limit': 3,
                          'context': {'active_test': False}})
            print('Numero terminado en ' + num[-4:] + ': ' + str(len(leads)) + ' lead(s)')
            for l in leads:
                print('- id=' + str(l['id']) + ' | ' + corto(l.get('name')) + ' | etiquetas=' + str(l.get('tag_ids')))
        except Exception as e:
            print('No se pudo buscar el lead: ' + str(e)[:100])
    print('')
    print('Fin del diagnostico.')


if __name__ == '__main__':
    principal()
