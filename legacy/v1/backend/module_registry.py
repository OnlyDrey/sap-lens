"""SAP areas are distinct from customer domains and role-name rules."""
from copy import deepcopy

# IDs are stable. Parent/category distinguish products, components and submodules.
_ROWS = [
('FI','Financial Accounting','module',None,'DollarSign','#6f8fc5',['Finance']),
('FI-AA','Asset Accounting','submodule','FI','Building2','#8799c5',[]),
('FI-AP','Accounts Payable','submodule','FI','DollarSign','#5f8dab',[]),
('FI-AR','Accounts Receivable','submodule','FI','DollarSign','#739cb8',[]),
('CO','Controlling','module',None,'BarChart2','#a184bc',[]),
('CO-PA','Profitability Analysis','submodule','CO','BarChart2','#ac92c1',[]),
('TRM','Treasury and Risk Management','functional-area',None,'DollarSign','#7590a7',[]),
('FSCM','Financial Supply Chain Management','functional-area',None,'DollarSign','#789ca8',[]),
('BPC','SAP Business Planning and Consolidation','product',None,'BarChart2','#947db0',[]),
('MM','Materials Management','module',None,'Package','#b08b60',[]),
('MM-PUR','Purchasing','submodule','MM','Package','#b99d6a',[]),
('MM-IM','Inventory Management','submodule','MM','Warehouse','#9b9866',[]),
('SD','Sales and Distribution','module',None,'TrendingUp','#629c9b',[]),
('LE','Logistics Execution','module',None,'Truck','#6e9d90',[]),
('LE-TRA','Transportation','submodule','LE','Truck','#7aa398',[]),
('WM','Warehouse Management','module',None,'Warehouse','#8da16d',[]),
('EWM','Extended Warehouse Management','functional-area',None,'Warehouse','#69a68e',[]),
('TM','Transportation Management','functional-area',None,'Truck','#76979d',[]),
('SCM','SAP Supply Chain Management','product',None,'Package','#a39e6a',[]),
('APO','Advanced Planning and Optimization','component','SCM','BarChart2','#9d90b9',[]),
('SRM','SAP Supplier Relationship Management','product',None,'Package','#b49c7b',[]),
('PP','Production Planning and Control','module',None,'Cog','#83a66c',[]),
('PP-PI','Production Planning for Process Industries','submodule','PP','Cog','#96ae75',[]),
('PM','Plant Maintenance','module',None,'Wrench','#b2a164',[]),
('QM','Quality Management','module',None,'CheckCircle','#b47f87',[]),
('PLM','Product Lifecycle Management','functional-area',None,'Layers','#8f91ae',[]),
('EHS','Environment, Health and Safety','functional-area',None,'Leaf','#78a18b',[]),
('EHSM','Environment, Health and Safety Management','functional-area',None,'Leaf','#89aa8a',[]),
('PS','Project System','module',None,'FolderKanban','#8793bc',[]),
('RE-FX','Flexible Real Estate Management','functional-area',None,'Building2','#9c93b1',[]),
('PSM','Public Sector Management','functional-area',None,'Building2','#a699ba',[]),
('CS','Customer Service','module',None,'Wrench','#b49776',[]),
('CRM','SAP Customer Relationship Management','product',None,'Users','#b3879c',[]),
('HCM','Human Capital Management','product',None,'Users','#a38ca9',['SAP HCM']),
('HR','Human Resources','module','HCM','Users','#af93ad',[]),
('PA','Personnel Administration','submodule','HR','Users','#ba9bae',[]),
('OM','Organizational Management','submodule','HR','Users','#a78faf',[]),
('PY','Payroll','submodule','HR','Users','#b49aaf',[]),
('CA','Cross-Application Components','component',None,'Layers','#8799a6',[]),
('BC','Basis Components','technical-component',None,'Server','#8196ac',['BASIS']),
('ABAP','ABAP Platform','technology',None,'Code','#908cac',[]),
('BW','SAP Business Warehouse','product',None,'Database','#6599b0',[]),
('BI','Business Intelligence','functional-area','BW','BarChart2','#7fa0b9',[]),
('GRC','Governance, Risk and Compliance','product',None,'Shield','#9f8eaa',[]),
('MDG','SAP Master Data Governance','product',None,'Database','#7d9eaa',[]),
('DMS','Document Management','component','CA','FileText','#929aa6',[]),
('BTP','SAP Business Technology Platform','product',None,'Globe','#8b93c2',[]),
('IS-U','SAP Utilities','industry-solution',None,'Building2','#70a2a5',['Utilities']),
('UNCLASSIFIED','Unclassified','fallback',None,'Hash','#8793a2',[]),
]
REGISTRY = {r[0]:dict(id=r[0], abbreviation=r[0], name=r[1], category=r[2], parent=r[3],
                         icon=r[4], color=r[5], aliases=r[6], enabled=True, display_name=None)
            for r in _ROWS}


def normalize(value):
    return str(value or '').strip().upper().replace('_','-').replace(' ', '')


_LOOKUP = {normalize(alias):code for code,item in REGISTRY.items() for alias in [code,*item['aliases']]}


def resolve_module(value):
    return _LOOKUP.get(normalize(value))


def discovered_color(value):
    # Bounded FNV-1a over normalized Unicode code points, shared with ModuleRegistry.tsx.
    # A fixed palette and stable ID hash are independent of registry ordering.
    palette = ('#6f8fc5', '#a184bc', '#b08b60', '#629c9b', '#8da16d', '#b47f87', '#6599b0', '#b3879c')
    fingerprint = 2166136261
    for character in normalize(str(value or '')[:256]):
        fingerprint = ((fingerprint ^ ord(character)) * 16777619) & 0xffffffff
    return palette[fingerprint % len(palette)]


def module_definition(value, overrides=None):
    code = resolve_module(value)
    if not code:
        return {**REGISTRY['UNCLASSIFIED'], 'id':str(value or 'UNCLASSIFIED'),
                'abbreviation':str(value or 'UNCLASSIFIED'), 'name':str(value or 'Unclassified'),
                'color':discovered_color(value) if value else REGISTRY['UNCLASSIFIED']['color']}
    item = deepcopy(REGISTRY[code])
    override = (overrides or {}).get(code)
    if override:
        item.update(override.model_dump(exclude_none=True) if hasattr(override,'model_dump') else override)
    if item['display_name']: item['name'] = item['display_name']
    return item


def registry_list(overrides=None):
    # Editors need canonical defaults even while effective saved overrides are active.
    return [{**module_definition(code, overrides), 'default_color':REGISTRY[code]['color'],
             'default_icon':REGISTRY[code]['icon'], 'default_name':REGISTRY[code]['name']}
            for code in REGISTRY]
