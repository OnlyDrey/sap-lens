"""SAP areas are distinct from customer domains and role-name rules."""
from copy import deepcopy

# IDs are stable. Parent/category distinguish products, components and submodules.
_ROWS = [
('FI','Financial Accounting','module',None,'DollarSign','#3d4d8a',['Finance']),
('FI-AA','Asset Accounting','submodule','FI','Building2','#3d4d8a',[]),
('FI-AP','Accounts Payable','submodule','FI','DollarSign','#3d4d8a',[]),
('FI-AR','Accounts Receivable','submodule','FI','DollarSign','#3d4d8a',[]),
('CO','Controlling','module',None,'BarChart2','#5a0090',[]),
('CO-PA','Profitability Analysis','submodule','CO','BarChart2','#5a0090',[]),
('TRM','Treasury and Risk Management','functional-area',None,'DollarSign','#3d4d8a',[]),
('FSCM','Financial Supply Chain Management','functional-area',None,'DollarSign','#3d4d8a',[]),
('BPC','SAP Business Planning and Consolidation','product',None,'BarChart2','#5a0090',[]),
('MM','Materials Management','module',None,'Package','#c44d10',[]),
('MM-PUR','Purchasing','submodule','MM','Package','#c44d10',[]),
('MM-IM','Inventory Management','submodule','MM','Warehouse','#c44d10',[]),
('SD','Sales and Distribution','module',None,'TrendingUp','#1d5a6e',[]),
('LE','Logistics Execution','module',None,'Truck','#1d5a6e',[]),
('LE-TRA','Transportation','submodule','LE','Truck','#1d5a6e',[]),
('WM','Warehouse Management','module',None,'Warehouse','#0a3848',[]),
('EWM','Extended Warehouse Management','functional-area',None,'Warehouse','#0a3848',[]),
('TM','Transportation Management','functional-area',None,'Truck','#1d5a6e',[]),
('SCM','SAP Supply Chain Management','product',None,'Package','#c44d10',[]),
('APO','Advanced Planning and Optimization','component','SCM','BarChart2','#5a0090',[]),
('SRM','SAP Supplier Relationship Management','product',None,'Package','#c44d10',[]),
('PP','Production Planning and Control','module',None,'Cog','#1a4d28',[]),
('PP-PI','Production Planning for Process Industries','submodule','PP','Cog','#1a4d28',[]),
('PM','Plant Maintenance','module',None,'Wrench','#9a6c00',[]),
('QM','Quality Management','module',None,'CheckCircle','#8b1a1a',[]),
('PLM','Product Lifecycle Management','functional-area',None,'Layers','#4a5568',[]),
('EHS','Environment, Health and Safety','functional-area',None,'Leaf','#1a4d28',[]),
('EHSM','Environment, Health and Safety Management','functional-area',None,'Leaf','#1a4d28',[]),
('PS','Project System','module',None,'FolderKanban','#1e2d78',[]),
('RE-FX','Flexible Real Estate Management','functional-area',None,'Building2','#1e2d78',[]),
('PSM','Public Sector Management','functional-area',None,'Building2','#1e2d78',[]),
('CS','Customer Service','module',None,'Wrench','#9a6c00',[]),
('CRM','SAP Customer Relationship Management','product',None,'Users','#162340',[]),
('HCM','Human Capital Management','product',None,'Users','#162340',['SAP HCM']),
('HR','Human Resources','module','HCM','Users','#162340',[]),
('PA','Personnel Administration','submodule','HR','Users','#162340',[]),
('OM','Organizational Management','submodule','HR','Users','#162340',[]),
('PY','Payroll','submodule','HR','Users','#162340',[]),
('CA','Cross-Application Components','component',None,'Layers','#4a5568',[]),
('BC','Basis Components','technical-component',None,'Server','#374151',['BASIS']),
('ABAP','ABAP Platform','technology',None,'Code','#374151',[]),
('BW','SAP Business Warehouse','product',None,'Database','#374151',[]),
('BI','Business Intelligence','functional-area','BW','BarChart2','#374151',[]),
('GRC','Governance, Risk and Compliance','product',None,'Shield','#374151',[]),
('MDG','SAP Master Data Governance','product',None,'Database','#374151',[]),
('DMS','Document Management','component','CA','FileText','#4a5568',[]),
('BTP','SAP Business Technology Platform','product',None,'Globe','#374151',[]),
('IS-U','SAP Utilities','industry-solution',None,'Building2','#1d5a6e',['Utilities']),
('UNCLASSIFIED','Unclassified','fallback',None,'Hash','#64748b',[]),
]
REGISTRY = {r[0]:dict(id=r[0], abbreviation=r[0], name=r[1], category=r[2], parent=r[3],
                         icon=r[4], color=r[5], aliases=r[6], enabled=True, display_name=None)
            for r in _ROWS}


def normalize(value):
    return str(value or '').strip().upper().replace('_','-').replace(' ', '')


_LOOKUP = {normalize(alias):code for code,item in REGISTRY.items() for alias in [code,*item['aliases']]}


def resolve_module(value):
    return _LOOKUP.get(normalize(value))


def module_definition(value, overrides=None):
    code = resolve_module(value)
    if not code:
        return {**REGISTRY['UNCLASSIFIED'], 'id':str(value or 'UNCLASSIFIED'),
                'abbreviation':str(value or 'UNCLASSIFIED'), 'name':str(value or 'Unclassified')}
    item = deepcopy(REGISTRY[code])
    override = (overrides or {}).get(code)
    if override:
        item.update(override.model_dump(exclude_none=True) if hasattr(override,'model_dump') else override)
    if item['display_name']: item['name'] = item['display_name']
    return item


def registry_list(overrides=None):
    return [module_definition(code, overrides) for code in REGISTRY]
