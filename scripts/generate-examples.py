"""Generate the three fully invented examples; never reads SAP or employee inputs."""
import csv
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ROLE_FIELDS='FUNCTION_KEY AGR_NAME TEXT CHILD_AGR CHILD_AGR_TEXT PARENT_AGR Effective_Role TCODE TTEXT'.split()
USER_FIELDS='USERNAME ROLE_NAME USER_GROUP FIRST_NAME LAST_NAME EMAIL USER_VALID_FROM USER_VALID_TO ROLE_VALID_FROM ROLE_VALID_TO USER_LOCKED USER_TYPE'.split()
EMPLOYEE_FIELDS='Site Name SamAccountName UserPrincipalName Mail Department Title Enabled DistinguishedName ManagerDN ManagerName ManagerSamAccountName ManagerMail ManagerDepartment ManagerTitle ManagerLookupStatus'.split()
TCODES=['MIGO','ME21N','ME23N','ME51N','ME53N','FB03','VA03','SU01']


def catalogue_name(number):
    name=f'ZC:SYN:ROLE_{number:03d}'
    return name+(':*' if number%20==0 else ':AB*' if number%5==0 else ':ABC' if number%3==0 else '')


def assigned_name(number,user):
    if number==15:return 'ZC:SYN:ROLE_015:ABC' # Equal-specificity catalogue patterns remain ambiguous.
    return catalogue_name(number).replace(':AB*',':ABC' if user%2 else ':ABD').replace(':*',':ABC' if user%2 else ':ABD')


def releases():
    return [f'ZO:MM:SYN:{kind}_REL_ST_{group}_{strategy}:SYN' for kind in ('PR','PO') for group in ('Q7','Q8') for strategy in ('R2','R3')]


def email(number):
    return '' if number%13==0 else 'shared@example.org' if number in (10,11) else f'person{number:03d}@example.org'


def write(name,fields,rows,delimiter=','):
    path=ROOT/'examples'/name
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,delimiter=delimiter);writer.writeheader();writer.writerows(rows)
    print(name,'records',len(rows))


def generate():
    roles=[]
    for number in range(1,121):
        for offset in range(3):
            code='' if number==119 else TCODES[(number+offset)%len(TCODES)]
            roles.append(dict(FUNCTION_KEY='' if number==37 else ['FI','MM','SD','BC'][number%4],AGR_NAME=catalogue_name(number),
                TEXT='' if number==41 else f'Synthetic catalogue role {number:03d}',CHILD_AGR=f'ZS_SYN_{number:03d}',
                CHILD_AGR_TEXT=f'Synthetic technical relationship {number:03d}',PARENT_AGR=f'ZP_SYN_{number:03d}',
                Effective_Role=f'ZE_SYN_{number:03d}',TCODE=code,TTEXT='Public SAP transaction example' if code else ''))
    for pattern,child in [('ZC:SYN:ROLE_005:*','ZS_SYN_BROAD005'),('zc:syn:role_015:ab*','ZS_SYN_ALT015')]:
        roles.append(dict(FUNCTION_KEY='MM',AGR_NAME=pattern,TEXT='Synthetic overlapping catalogue pattern',CHILD_AGR=child,CHILD_AGR_TEXT='Synthetic pattern relationship',PARENT_AGR='',Effective_Role='',TCODE='MIGO',TTEXT='Public SAP transaction example'))
    for name in releases():
        roles.append(dict(FUNCTION_KEY='MM',AGR_NAME=name,TEXT='Synthetic release naming example',CHILD_AGR='',CHILD_AGR_TEXT='',PARENT_AGR='',Effective_Role='',TCODE='',TTEXT=''))
    roles.append(roles[0].copy())
    users=[]
    for number in range(1,71):
        base=dict(USERNAME=f'SYN_U{number:03d}',USER_GROUP='UNLICENSED' if number%19==0 else f'EXAMPLE_{"ABC"[number%3]}',FIRST_NAME=f'Example{number:03d}',LAST_NAME='Person',EMAIL=email(number),
            USER_VALID_FROM='' if number%16==0 else '2999-01-01' if number%17==0 else '2000-01-01',USER_VALID_TO='' if number%16==0 else '2001-01-01' if number%10==0 else '9999-12-31',
            USER_LOCKED='64' if number%9==0 else '' if number%8==0 else '0',USER_TYPE='X' if number==66 else 'B' if number%11==0 else 'S' if number%17==0 else 'A')
        names=[assigned_name(n,number) for n in ([1,2,3] if number==1 else [1,2,4] if number==2 else [(number*3+offset)%120+1 for offset in range(3)])] if number<68 else ['']
        if number<=30:names += [releases()[number%8],releases()[(number+1)%8]]
        if number==12:names.append('ZC:SYN:UNMAPPED:XYZ')
        if number==18:names.append('ZO:SYN:UNPARSED')
        if number==8:names.append('ZS_SYN_008')
        for index,name in enumerate(names):
            start,end=('','') if not name else ('2000-01-01','2001-01-01') if number%7==0 and index==1 else ('2999-01-01','9999-12-31') if number%14==0 and index==2 else ('2000-01-01','') if number%12==0 and index==0 else ('2000-01-01','9999-12-31')
            users.append(dict(**base,ROLE_NAME=name,ROLE_VALID_FROM=start,ROLE_VALID_TO=end))
    users += [row.copy() for row in users[:5]]
    # A distinct interval is evidence, not an identical duplicate to collapse.
    historical=users[0].copy();historical.update(ROLE_VALID_FROM='1999-01-01',ROLE_VALID_TO='1999-12-31');users.append(historical)
    employees=[]
    for number in range(1,76):
        manager=None if number==1 else 71 if number==6 else number if number==3 else 4 if number==8 else 2 if number%5==0 else 1
        manager_mail='' if manager is None else 'absent.manager@example.org' if number%11==0 else email(manager)
        employees.append(dict(Site='Example Site A',Name=f'Example{number:03d} Person',SamAccountName='' if number%23==0 else f'syn_person{number:03d}',UserPrincipalName=f'person{number:03d}@example.org',
            Mail=email(4) if number==5 else email(number),Department=f'Example Unit {"ABC"[number%3]}',Title='' if number%12==0 else 'Example Analyst; "Synthetic"' if number==22 else 'Example Analyst',
            Enabled='false' if number%7==0 else '' if number%10==0 else 'true',DistinguishedName=f'CN=person{19 if number==20 else number:03d},OU=Examples,DC=example,DC=org',
            ManagerDN='' if manager is None else f'CN=person{manager:03d},OU=Examples,DC=example,DC=org',ManagerName='' if manager is None else f'Example{manager:03d} Person',
            ManagerSamAccountName='' if manager is None else f'syn_person{manager:03d}',ManagerMail=manager_mail,ManagerDepartment='' if manager is None else 'Example Unit A',
            ManagerTitle='' if manager is None else 'Example Analyst',ManagerLookupStatus='missing' if manager is None else 'synthetic'))
    write('role-catalogue.example.csv',ROLE_FIELDS,roles)
    write('user-access.example.csv',USER_FIELDS,users)
    write('employee-directory.example.csv',EMPLOYEE_FIELDS,employees,';')


if __name__=='__main__':generate()
