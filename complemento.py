"""Comprobaciones complementarias: recall a igual tasa de alerta, B vs A, y sensibilidad sin 2024-2."""
import ast, warnings, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier
warnings.filterwarnings("ignore")
SEED=42; rng=np.random.default_rng(SEED); B=2000
PATH="/mnt/user-data/uploads/dataset_desercion_primer_nivel__1_.xlsx"; OUT="/home/claude/analisis/out"
raw=pd.read_excel(PATH); raw["y"]=(raw.via_salida=="REPRUEBA_INASISTENCIAS").astype(int)
G=raw[(raw.estado_periodo=="CERRADO")&(raw.modalidad=="PRESENCIAL")&(raw.via_salida!="RETIRO_VOLUNTARIO")&(raw.tiene_registro_asistencia=="SI")].copy()
G["prop_dias_asistidos_d28"]=G.dias_asistidos_d28/G.dias_con_clase_d28

def feats(d,c):
    X=pd.DataFrame(index=d.index)
    for k in ["pct_inasistencia_d28","max_pct_inasistencia_asig_d28","max_pct_inasist_sobre_total_d28","dia_primera_asistencia","prop_dias_asistidos_d28","n_asignaturas_matriculadas"]: X[k]=d[k]
    if c=="B":
        X["puntaje_admision"]=d.puntaje_admision; X["edad_anios"]=d.edad_anios; X["sexo_M"]=(d.sexo=="M").astype(float)
        X["jornada_nocturna"]=(d.jornada=="NOCTURNA").astype(float); X["jornada_vespertina"]=(d.jornada=="VESPERTINA").astype(float)
        X["trabaja"]=d.estado_laboral.map({"SI":1.0,"NO":0.0}); X["nse_ordinal"]=d.nivel_socioeconomico.str[1].astype(float)
        X["log_ingreso_pc"]=np.log1p(d.ingreso_per_capita_hogar)
        X["colegio_publico"]=d.tipo_colegio.map(lambda v: np.nan if pd.isna(v) else float(v=="PUBLICO"))
        X["primera_generacion"]=d.primera_generacion_superior.map({"SI":1.0,"NO":0.0}); X["recibe_bdh"]=(d.bono_desarrollo_humano=="SI").astype(float)
        X["reside_machala"]=d.zona_residencia.map(lambda v: np.nan if pd.isna(v) else float(v=="MACHALA")); X["soltero"]=(d.estado_civil=="SOLTERO").astype(float)
    return X

hp=pd.read_excel(f"{OUT}/resultados_preliminares.xlsx",sheet_name="9_hiperparametros_umbrales")
hp=hp[hp.modelo!="Línea base"]; P={(r.modelo,r.conjunto):ast.literal_eval(r["hiperparámetros"]) for _,r in hp.iterrows()}

def build(n,params,ytr):
    imp=("imp",SimpleImputer(strategy="median")); p={k.replace("m__",""):v for k,v in params.items()}
    if n=="Regresión Logística": return Pipeline([imp,("sc",StandardScaler()),("m",LogisticRegression(class_weight="balanced",max_iter=3000,**p))])
    if n=="Random Forest": return Pipeline([imp,("m",RandomForestClassifier(n_estimators=300,class_weight="balanced_subsample",n_jobs=-1,random_state=SEED,**p))])
    spw=(ytr==0).sum()/(ytr==1).sum()
    return Pipeline([imp,("m",XGBClassifier(subsample=0.8,colsample_bytree=0.8,min_child_weight=5,scale_pos_weight=spw,eval_metric="logloss",tree_method="hist",n_jobs=4,random_state=SEED,**p))])

def fit_predict(train_periods,val="2025-2"):
    tr=G[G.periodo.isin(train_periods)]; va=G[G.periodo==val]; out={"Línea base (asistencia)":va.pct_inasistencia_d28.values}
    for (n,c),p in P.items():
        m=build(n,p,tr.y.values).fit(feats(tr,c),tr.y.values); out[f"{n} [{c}]"]=m.predict_proba(feats(va,c))[:,1]
    return out,va.y.values

def recall_at(y,s,k,tiebreak):
    s2=s+tiebreak*1e-9; n=int(round(k*len(y))); idx=np.argsort(-s2)[:n]; return y[idx].sum()/y.sum()

# ---- 1) recall a igual tasa de alerta (entrenamiento 4 periodos, validación 2025-2)
scores,yva=fit_predict(["2023-2","2024-1","2024-2","2025-1"])
tb=rng.random(len(yva)); rows=[]
for k in [0.2,0.3,0.4,0.5]:
    for nm,s in scores.items():
        pt=recall_at(yva,s,k,tb); bs=[]
        for _ in range(B):
            i=rng.integers(0,len(yva),len(yva)); yb=yva[i]
            if yb.sum()==0: continue
            bs.append(recall_at(yb,s[i],k,tb[i]))
        rows.append(dict(tasa_alerta_fija=f"{int(k*100)} %",modelo=nm,recall=round(pt,3),IC95=f"[{np.percentile(bs,2.5):.2f}; {np.percentile(bs,97.5):.2f}]"))
t_alerta=pd.DataFrame(rows)

# ---- 2) B vs A (diferencia pareada AUC-PR)
rows=[]
for n in ["Regresión Logística","Random Forest","XGBoost"]:
    a,b=scores[f"{n} [A]"],scores[f"{n} [B]"]; d=[]
    for _ in range(B):
        i=rng.integers(0,len(yva),len(yva)); yb=yva[i]
        if yb.sum()==0: continue
        d.append(average_precision_score(yb,b[i])-average_precision_score(yb,a[i]))
    rows.append(dict(modelo=n,AUC_PR_A=round(average_precision_score(yva,a),3),AUC_PR_B=round(average_precision_score(yva,b),3),
                     dif_B_menos_A=round(float(np.mean(d)),3),IC95=f"[{np.percentile(d,2.5):.3f}; {np.percentile(d,97.5):.3f}]"))
t_ba=pd.DataFrame(rows)

# ---- 3) sensibilidad: sin el periodo 2024-2
sc2,yva2=fit_predict(["2023-2","2024-1","2025-1"]); rows=[]
base=sc2["Línea base (asistencia)"]
for nm,s in sc2.items():
    ap=average_precision_score(yva2,s); ar=roc_auc_score(yva2,s); b_ap=[];dd=[]
    for _ in range(B):
        i=rng.integers(0,len(yva2),len(yva2)); yb=yva2[i]
        if yb.sum()==0: continue
        a1=average_precision_score(yb,s[i]); b_ap.append(a1); dd.append(a1-average_precision_score(yb,base[i]))
    rows.append(dict(modelo=nm,AUC_PR=round(ap,3),AUC_PR_IC95=f"[{np.percentile(b_ap,2.5):.3f}; {np.percentile(b_ap,97.5):.3f}]",AUC_ROC=round(ar,3),
                     dif_vs_base="" if nm.startswith("Línea") else round(float(np.mean(dd)),3),
                     dif_IC95="" if nm.startswith("Línea") else f"[{np.percentile(dd,2.5):.3f}; {np.percentile(dd,97.5):.3f}]"))
t_sin=pd.DataFrame(rows)

# ---- 4) calidad de la asistencia por periodo
q=[]
for p,g in G.groupby("periodo"):
    q.append(dict(periodo=p,estudiantes=len(g),pct_con_alguna_inasistencia_d28=round((g.pct_inasistencia_d28>0).mean()*100,1),
                  positivos=int(g.y.sum()),positivos_sin_inasistencia_d28_pct=round((g[g.y==1].pct_inasistencia_d28==0).mean()*100,1),
                  mediana_pct_inasist_positivos=round(g[g.y==1].pct_inasistencia_d28.median(),1),
                  mediana_pct_inasist_negativos=round(g[g.y==0].pct_inasistencia_d28.median(),1)))
t_cal=pd.DataFrame(q)

with pd.ExcelWriter(f"{OUT}/resultados_preliminares.xlsx",engine="openpyxl",mode="a",if_sheet_exists="replace") as xw:
    t_alerta.to_excel(xw,sheet_name="10_recall_igual_alerta",index=False); t_ba.to_excel(xw,sheet_name="11_B_vs_A",index=False)
    t_sin.to_excel(xw,sheet_name="12_sin_2024-2",index=False); t_cal.to_excel(xw,sheet_name="13_calidad_asistencia",index=False)
    for nm in ["10_recall_igual_alerta","11_B_vs_A","12_sin_2024-2","13_calidad_asistencia"]:
        ws=xw.book[nm]
        for c in ws[1]: c.font=c.font.copy(bold=True)
        for col in ws.columns:
            w=max(len(str(c.value)) if c.value is not None else 0 for c in col); ws.column_dimensions[col[0].column_letter].width=min(max(12,w+2),60)
pd.set_option("display.width",250); pd.set_option("display.max_columns",30)
print("\n== Recall a igual tasa de alerta (validación 2025-2)"); print(t_alerta.pivot(index="modelo",columns="tasa_alerta_fija",values="recall").to_string())
print(t_alerta[t_alerta.tasa_alerta_fija=="40 %"].to_string(index=False))
print("\n== B vs A"); print(t_ba.to_string(index=False))
print("\n== Sin 2024-2 (entrena 2023-2, 2024-1, 2025-1; valida 2025-2)"); print(t_sin.to_string(index=False))
print("\n== Calidad asistencia por periodo"); print(t_cal.to_string(index=False))
