"""Small physically complete four-direction input set; contains no business data."""
from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd
import xarray as xr

DIRECTIONS = ['ТС5/Онлайн', 'ТСХ/Онлайн', 'ТС5/Оффлайн', 'ТСХ/Оффлайн']


def write_inputs(root: Path) -> dict:
    roots={k:root/k for k in ['package','data','source']}
    for directory in roots.values():directory.mkdir(parents=True)
    def write(role, value):
        p=roots['package']/role;p.write_text(json.dumps(value,ensure_ascii=False));return p
    registry=[];spend=[];panel=[];index=[];denom=[];fits={};posteriors={}
    digest=lambda p:hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
    for n,segment in enumerate(DIRECTIONS):
        net,ch=segment.split('/');key=f'synthetic_{n}';fit=segment+'::turnover_per_user'
        stem=fit.replace('/','_').replace('::','__')
        dates=pd.date_range('2025-01-01',periods=12)
        f=pd.DataFrame({'date':dates,'geo_label':'synthetic_geo','network':net,'channel':ch,
                        'unique_users':10.,'orders_cnt':20.,'population_k':2.,'spend_TV':30.})
        panel.append(f)
        ix=f[['date','geo_label','network','channel']].assign(fit_key=fit,row_position=range(12));index.append(ix)
        denom.append(f[['date','geo_label','population_k','unique_users','orders_cnt']].assign(segment=segment))
        registry.append({'campaign_key':key,'campaign_id':'synthetic-name','campaign_name':'Синтетическая кампания',
                         'segment':segment,'start_date':dates[3],'end_date':dates[4],
                         'source_budget_rub':20.,'panel_budget_rub':20.,'has_federal_rows':False,
                         'source_declared_windows':'["2025-01-04 / 2025-01-05"]','source_declared_window_count':1})
        spend.append(f.iloc[3:5][['date','geo_label','network','channel']].assign(campaign_key=key,media_channel='TV',spend_rub=10.,panel_covered=True))
        transform={'l_max':2,'channels':['TV'],'spend_active':['spend_TV'],'geos':['synthetic_geo'], 'x_scale_geo':[[5.]],'y_scale':3.}
        write('fit_transform_'+stem+'.json',transform)
        posterior='posterior_'+stem+'.nc'
        ds=xr.Dataset({'alpha':(('chain','draw','channel'),np.array([.2,.4,.6,.8]).reshape(2,2,1)),
                       'lam':(('chain','draw','channel'),np.ones((2,2,1))),
                       'beta':(('chain','draw','channel'),np.ones((2,2,1))*2)},coords={'chain':[0,1],'draw':[0,1],'channel':['TV']})
        ds.to_netcdf(roots['package']/posterior,engine='h5netcdf',group='posterior')
        fits[fit]={**transform,'posterior_file':posterior}
        posteriors[fit]=digest(roots['package']/posterior)
    pd.concat(panel).to_parquet(roots['data']/'panel.parquet',index=False)
    pd.concat(index).to_parquet(roots['package']/'fit_design_row_index.parquet',index=False)
    pd.concat(denom).to_csv(roots['package']/'target_denominator_metadata.csv',index=False)
    pd.DataFrame(registry).to_parquet(roots['source']/'A1_CAMPAIGN_REGISTRY.parquet',index=False)
    pd.concat(spend).to_parquet(roots['source']/'A1_ALLOCATED_CAMPAIGN_SPEND.parquet',index=False)
    source={'input_artifacts':{},'output_artifacts':{name:{'sha256':digest(roots['source']/name)} for name in ['A1_CAMPAIGN_REGISTRY.parquet','A1_ALLOCATED_CAMPAIGN_SPEND.parquet']}}
    (roots['source']/'source_manifest.json').write_text(json.dumps(source))
    write('fit_design_metadata.json',{'fits':fits})
    write('run_config.json',{'train_start':'2025-01-01','train_end':'2025-01-12','center_media_response':False,'media_grouping_config':{}})
    write('model_manifest.json',{'package_input_fingerprint':'a'*64,'evidence_sha256':{},'posterior_sha256':posteriors})
    spec={'files':{},'model_package_id':'synthetic_package','package_fingerprint':'a'*64,'posterior_draws':4,'goldens':{}}
    def add(role,root_name,name):spec['files'][role]={'root':root_name,'path':name,'sha256':digest(roots[root_name]/name)}
    for role,name in [('model_manifest','model_manifest.json'),('run_config','run_config.json'),('fit_design_metadata','fit_design_metadata.json'),('fit_design_row_index','fit_design_row_index.parquet'),('denominators','target_denominator_metadata.csv')]:add(role,'package',name)
    for fit,meta in fits.items():
        add('transform:'+fit,'package','fit_transform_'+fit.replace('/','_').replace('::','__')+'.json')
        add('posterior:'+fit,'package',meta['posterior_file'])
    add('panel','data','panel.parquet')
    for role,name in [('registry','A1_CAMPAIGN_REGISTRY.parquet'),('spend','A1_ALLOCATED_CAMPAIGN_SPEND.parquet'),('source_manifest','source_manifest.json')]:add(role,'source',name)
    (root/'input.json').write_text(json.dumps(spec))
    return {'spec':spec,'roots':roots}
