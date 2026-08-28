import os
import platform
import subprocess


def notify_qualified(status, db=None):
    if os.getenv('RADAR_MAC_NOTIFICATIONS','1').strip().lower() not in ('1','true','yes','on'):
        return {'state':'DISABLED'}
    packages=status.get('manual_packages') or []
    if not packages:
        return {'state':'NO_QUALIFIED_PACKAGE'}
    if platform.system()!='Darwin':
        return {'state':'NON_MACOS'}
    sent=0
    for c in packages:
        addr=(c.get('collection') or '').lower()
        key='notified:'+addr
        fingerprint=f"{c.get('qualification_path')}:{c.get('score')}:{c.get('mint_price_eth')}"
        if db is not None and db.get_meta(key)==fingerprint:
            continue
        name=c.get('name') or c.get('ticker') or addr[:10]
        score=c.get('score')
        price='FREE' if c.get('mint_price_eth')==0 else (str(c.get('mint_price_eth'))+' ETH' if c.get('mint_price_eth') is not None else 'UNKNOWN')
        msg=f'{name} | score {score}/100 | mint {price} | wallet remains manual'
        script='display notification '+repr(msg)+' with title '+repr('Robinhood Mint Radar')
        try:
            subprocess.run(['/usr/bin/osascript','-e',script],check=True,timeout=8,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            sent+=1
            if db is not None: db.set_meta(key,fingerprint)
        except Exception:
            return {'state':'NOTIFICATION_FAILED','sent':sent}
    return {'state':'SENT' if sent else 'DEDUPED','sent':sent}
