"""
Análisis preliminar (presentación de avances)
Sistema de alertas tempranas - no continuidad en la carrera, primer nivel
Alcance: modalidad PRESENCIAL, periodos CERRADOS con desenlace (2023-2 a 2025-2).

Uso:  python analisis_preliminar.py ruta/al/dataset.xlsx  carpeta_salida
"""
import sys, json, warnings
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.model_selection import RepeatedStratifiedKFold, StratifiedKFold, GridSearchCV, cross_val_predict
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, roc_auc_score, precision_recall_curve
from sklearn.base import clone
from xgboost import XGBClassifier
from imblearn.pipeline import Pipeline as ImbPipeline
from imblearn.over_sampling import SMOTE
import shap

warnings.filterwarnings("ignore")
SEED = 42
RECALL_OBJETIVO = 0.70      # punto de operación declarado ANTES de evaluar en validación
B_BOOT = 2000
PATH = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/dataset_desercion_primer_nivel__1_.xlsx"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/home/claude/analisis/out"
rng = np.random.default_rng(SEED)

# ---------------------------------------------------------------- datos y alcance
raw = pd.read_excel(PATH)
raw["y"] = (raw.via_salida == "REPRUEBA_INASISTENCIAS").astype(int)
cer = raw[raw.estado_periodo == "CERRADO"].copy()
pres = cer[cer.modalidad == "PRESENCIAL"].copy()
G = pres[(pres.via_salida != "RETIRO_VOLUNTARIO") & (pres.tiene_registro_asistencia == "SI")].copy()
G["prop_dias_asistidos_d28"] = G.dias_asistidos_d28 / G.dias_con_clase_d28

def feats(d, conjunto):
    X = pd.DataFrame(index=d.index)
    X["pct_inasistencia_d28"] = d.pct_inasistencia_d28
    X["max_pct_inasistencia_asig_d28"] = d.max_pct_inasistencia_asig_d28
    X["max_pct_inasist_sobre_total_d28"] = d.max_pct_inasist_sobre_total_d28
    X["dia_primera_asistencia"] = d.dia_primera_asistencia
    X["prop_dias_asistidos_d28"] = d.prop_dias_asistidos_d28
    X["n_asignaturas_matriculadas"] = d.n_asignaturas_matriculadas
    if conjunto == "B":
        X["puntaje_admision"] = d.puntaje_admision
        X["edad_anios"] = d.edad_anios
        X["sexo_M"] = (d.sexo == "M").astype(float)
        X["jornada_nocturna"] = (d.jornada == "NOCTURNA").astype(float)
        X["jornada_vespertina"] = (d.jornada == "VESPERTINA").astype(float)
        X["trabaja"] = d.estado_laboral.map({"SI": 1.0, "NO": 0.0})
        X["nse_ordinal"] = d.nivel_socioeconomico.str[1].astype(float)
        X["log_ingreso_pc"] = np.log1p(d.ingreso_per_capita_hogar)
        X["colegio_publico"] = d.tipo_colegio.map(lambda v: np.nan if pd.isna(v) else float(v == "PUBLICO"))
        X["primera_generacion"] = d.primera_generacion_superior.map({"SI": 1.0, "NO": 0.0})
        X["recibe_bdh"] = (d.bono_desarrollo_humano == "SI").astype(float)
        X["reside_machala"] = d.zona_residencia.map(lambda v: np.nan if pd.isna(v) else float(v == "MACHALA"))
        X["soltero"] = (d.estado_civil == "SOLTERO").astype(float)
    return X

TRAIN_P = ["2023-2", "2024-1", "2024-2", "2025-1"]
VAL_P = "2025-2"
tr, va = G[G.periodo.isin(TRAIN_P)], G[G.periodo == VAL_P]
ytr, yva = tr.y.values, va.y.values

# ---------------------------------------------------------------- perfilado
perf = []
for p, g in pres.groupby("periodo"):
    gg = G[G.periodo == p]
    perf.append(dict(periodo=p, estudiantes=len(g),
        aprueba=(g.via_salida == "PERMANECE_APRUEBA").sum(),
        reprueba_rendimiento=(g.via_salida == "PERMANECE_REPRUEBA_RENDIMIENTO").sum(),
        reprueba_inasistencias=(g.via_salida == "REPRUEBA_INASISTENCIAS").sum(),
        retiro_voluntario=(g.via_salida == "RETIRO_VOLUNTARIO").sum(),
        cambio_carrera=0, traslado=0,
        grupo_prediccion=len(gg), positivos=int(gg.y.sum()),
        tasa_positivos_pct=round(gg.y.mean() * 100, 1)))
perf = pd.DataFrame(perf)
tot = perf.drop(columns=["periodo", "tasa_positivos_pct"]).sum()
tot["tasa_positivos_pct"] = round(G.y.mean() * 100, 1); tot["periodo"] = "TOTAL"
perf = pd.concat([perf, pd.DataFrame([tot])], ignore_index=True)

alcance = pd.DataFrame([
    ["Filas en el archivo", len(raw)],
    ["Periodos cerrados con desenlace", cer.periodo.nunique()],
    ["Estudiantes en periodos cerrados", len(cer)],
    ["  de ellos, modalidad DUAL (fuera del alcance)", int((cer.modalidad == "DUAL").sum())],
    ["Estudiantes presenciales en periodos cerrados", len(pres)],
    ["  retiros voluntarios (grupo de detección)", int((pres.via_salida == "RETIRO_VOLUNTARIO").sum())],
    ["  casos de inasistencia irreversible al día 28 (presencial)", int((pres.irreversible_inasistencia_d28 == "SI").sum())],
    ["Grupo de predicción (presencial, con asistencia, sin retiro)", len(G)],
    ["  positivos (reprobados por inasistencias)", int(G.y.sum())],
    ["  tasa de positivos (%)", round(G.y.mean() * 100, 1)],
    ["Entrenamiento (2023-2 a 2025-1): estudiantes / positivos", f"{len(tr)} / {int(tr.y.sum())}"],
    ["Validación (2025-2): estudiantes / positivos", f"{len(va)} / {int(va.y.sum())}"],
    ["Techo de predictores (10 eventos por variable, entrenamiento)", int(tr.y.sum() // 10)],
    ["Positivos con aprobación agregada <=30% de inasistencia (regla agregada los pasaría a 0)",
        int(((G.y == 1) & (G.pct_inasistencia_final <= 30)).sum())],
], columns=["concepto", "valor"])

# ---------------------------------------------------------------- criterios (declarados antes de evaluar)
criterios = pd.DataFrame([
    ["C1", "El mejor modelo (elegido por AUC-PR en validación cruzada del entrenamiento) supera a la línea base de asistencia en AUC-PR de validación, con IC 95 % de la diferencia que excluya 0."],
    ["C2", f"Con el umbral fijado en entrenamiento para Recall >= {RECALL_OBJETIVO:.2f}, el modelo genera una tasa de alerta menor que la línea base en validación."],
    ["C3", "El modelo con variables de admisión/socioeconómicas (B) mejora a su versión solo con asistencia (A) en AUC-PR de validación."],
    ["C4", "Ningún subgrupo (sexo, nivel socioeconómico, jornada, zona) presenta una tasa de falsos negativos muy superior a la general (revisión descriptiva, subgrupos pequeños)."],
], columns=["criterio", "descripcion"])

# ---------------------------------------------------------------- línea base
def umbral_recall(score, y, objetivo):
    """Mayor umbral con recall >= objetivo (alerta si score >= umbral)."""
    cand = np.unique(score)[::-1]
    for t in cand:
        if (score[y == 1] >= t).mean() >= objetivo:
            return t
    return cand[-1]

def metricas(y, s, thr):
    pred = s >= thr
    tp = (pred & (y == 1)).sum(); fp = (pred & (y == 0)).sum(); fn = ((~pred) & (y == 1)).sum()
    rec = tp / max(tp + fn, 1); prec = tp / max(tp + fp, 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-9)
    return dict(AUC_PR=average_precision_score(y, s), AUC_ROC=roc_auc_score(y, s),
                Recall=rec, Precision=prec, F1=f1, Tasa_alerta=pred.mean())

base_tr = tr.pct_inasistencia_d28.values
base_va = va.pct_inasistencia_d28.values
thr_base = umbral_recall(base_tr, ytr, RECALL_OBJETIVO)

# ---------------------------------------------------------------- modelos
cv_tune = RepeatedStratifiedKFold(n_splits=5, n_repeats=2, random_state=SEED)
spw = (ytr == 0).sum() / (ytr == 1).sum()

def modelo(nombre):
    imp = ("imp", SimpleImputer(strategy="median"))
    if nombre == "Regresión Logística":
        pipe = Pipeline([imp, ("sc", StandardScaler()),
                         ("m", LogisticRegression(class_weight="balanced", max_iter=3000))])
        grid = {"m__C": [0.01, 0.1, 1, 10]}
    elif nombre == "Random Forest":
        pipe = Pipeline([imp, ("m", RandomForestClassifier(n_estimators=300, class_weight="balanced_subsample",
                                                            n_jobs=-1, random_state=SEED))])
        grid = {"m__max_depth": [4, 6, 10], "m__min_samples_leaf": [5, 15]}
    else:
        pipe = Pipeline([imp, ("m", XGBClassifier(subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                                                  scale_pos_weight=spw, eval_metric="logloss",
                                                  tree_method="hist", n_jobs=4, random_state=SEED))])
        grid = {"m__max_depth": [2, 3, 4], "m__n_estimators": [100, 300], "m__learning_rate": [0.03, 0.1]}
    return pipe, grid

NOMBRES = ["Regresión Logística", "Random Forest", "XGBoost"]
res = {}       # (nombre, conjunto) -> dict
for conj in ["A", "B"]:
    Xtr, Xva = feats(tr, conj), feats(va, conj)
    for n in NOMBRES:
        pipe, grid = modelo(n)
        gs = GridSearchCV(pipe, grid, scoring="average_precision", cv=cv_tune, n_jobs=1, refit=True)
        gs.fit(Xtr, ytr)
        best = gs.best_estimator_
        oof = cross_val_predict(clone(best), Xtr, ytr, cv=StratifiedKFold(5, shuffle=True, random_state=SEED),
                                method="predict_proba")[:, 1]
        thr = umbral_recall(oof, ytr, RECALL_OBJETIVO)
        pva = best.predict_proba(Xva)[:, 1]
        res[(n, conj)] = dict(cv_ap=gs.best_score_, params=gs.best_params_, thr=thr, pva=pva, best=best, Xtr=Xtr, Xva=Xva)
        print(f"{n} [{conj}] CV AUC-PR={gs.best_score_:.3f} {gs.best_params_}", flush=True)

# ---------------------------------------------------------------- evaluación en validación con IC
def boot(y, scores_thr, B=B_BOOT):
    """scores_thr: dict nombre -> (score, thr). Devuelve IC por métrica y diferencia AUC-PR vs línea base."""
    n = len(y); out = {k: {m: [] for m in ["AUC_PR", "AUC_ROC", "Recall", "Precision", "F1", "Tasa_alerta"]} for k in scores_thr}
    dif = {k: [] for k in scores_thr}
    for _ in range(B):
        idx = rng.integers(0, n, n)
        yb = y[idx]
        if yb.sum() == 0 or yb.sum() == n: continue
        ap_base = None
        for k, (s, t) in scores_thr.items():
            m = metricas(yb, s[idx], t)
            for mk, mv in m.items(): out[k][mk].append(mv)
            if k == "Línea base (asistencia)": ap_base = m["AUC_PR"]
        for k in scores_thr: dif[k].append(out[k]["AUC_PR"][-1] - ap_base)
    return out, dif

sc = {"Línea base (asistencia)": (base_va, thr_base)}
for (n, conj), r in res.items():
    sc[f"{n} [{conj}]"] = (r["pva"], r["thr"])
bo, bd = boot(yva, sc)

filas = []
for k, (s, t) in sc.items():
    m = metricas(yva, s, t)
    row = {"modelo": k}
    for mk in ["AUC_PR", "AUC_ROC", "Recall", "Precision", "F1", "Tasa_alerta"]:
        lo, hi = np.percentile(bo[k][mk], [2.5, 97.5])
        row[mk] = round(m[mk], 3); row[mk + "_IC95"] = f"[{lo:.3f}; {hi:.3f}]"
    if k != "Línea base (asistencia)":
        d = np.array(bd[k]); row["dif_AUC_PR_vs_base"] = round(float(np.mean(d)), 3)
        row["dif_IC95"] = f"[{np.percentile(d, 2.5):.3f}; {np.percentile(d, 97.5):.3f}]"
        row["CV_AUC_PR_entrenamiento"] = round(res[tuple([k.split(' [')[0], k.split('[')[1][0]])]["cv_ap"], 3)
    filas.append(row)
tabla_val = pd.DataFrame(filas)
prevalencia = yva.mean()

# mejor modelo por CV (no por validación)
mejor = max(res.keys(), key=lambda k: res[k]["cv_ap"])
mejorA = max([k for k in res if k[1] == "A"], key=lambda k: res[k]["cv_ap"])
print("Mejor por CV:", mejor, flush=True)

# ---------------------------------------------------------------- SMOTE vs pesos (en entrenamiento, CV repetida)
smote_rows = []
XtrB = feats(tr, "B")
for n in ["Regresión Logística", "Random Forest"]:
    pipe_w = clone(res[(n, "B")]["best"])
    ap_w = np.mean([average_precision_score(ytr[te], clone(pipe_w).fit(XtrB.iloc[trn], ytr[trn]).predict_proba(XtrB.iloc[te])[:, 1])
                    for trn, te in cv_tune.split(XtrB, ytr)])
    params = {k.replace("m__", ""): v for k, v in res[(n, "B")]["params"].items()}
    if n == "Regresión Logística":
        mm = LogisticRegression(max_iter=3000, **params)
        pipe_s = ImbPipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler()),
                              ("sm", SMOTE(random_state=SEED)), ("m", mm)])
    else:
        mm = RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=SEED, **params)
        pipe_s = ImbPipeline([("imp", SimpleImputer(strategy="median")), ("sm", SMOTE(random_state=SEED)), ("m", mm)])
    ap_s = np.mean([average_precision_score(ytr[te], clone(pipe_s).fit(XtrB.iloc[trn], ytr[trn]).predict_proba(XtrB.iloc[te])[:, 1])
                    for trn, te in cv_tune.split(XtrB, ytr)])
    smote_rows.append(dict(modelo=n, AUC_PR_pesos_de_clase=round(ap_w, 3), AUC_PR_SMOTE=round(ap_s, 3)))
tabla_smote = pd.DataFrame(smote_rows)

# ---------------------------------------------------------------- leave-one-period-out (robustez y subgrupos)
periodos = sorted(G.periodo.unique())
lopo_rows, pooled = [], {}
for conj in ["A", "B"]:
    XG = feats(G, conj)
    for n in NOMBRES:
        pipe, _ = modelo(n)
        pipe.set_params(**res[(n, conj)]["params"])
        oofp = pd.Series(index=G.index, dtype=float)
        for p in periodos:
            mtr, mte = (G.periodo != p).values, (G.periodo == p).values
            m = clone(pipe).fit(XG[mtr], G.y[mtr])
            oofp[mte] = m.predict_proba(XG[mte])[:, 1]
        pooled[(n, conj)] = oofp
        for p in periodos:
            mk = (G.periodo == p).values
            lopo_rows.append(dict(periodo=p, modelo=f"{n} [{conj}]", AUC_PR=average_precision_score(G.y[mk], oofp[mk]),
                                  AUC_ROC=roc_auc_score(G.y[mk], oofp[mk])))
for p in periodos:
    mk = (G.periodo == p).values
    lopo_rows.append(dict(periodo=p, modelo="Línea base (asistencia)",
                          AUC_PR=average_precision_score(G.y[mk], G.pct_inasistencia_d28[mk]),
                          AUC_ROC=roc_auc_score(G.y[mk], G.pct_inasistencia_d28[mk])))
lopo = pd.DataFrame(lopo_rows)
lopo_piv = lopo.pivot(index="modelo", columns="periodo", values="AUC_PR").round(3)
lopo_piv["media"] = lopo_piv.mean(axis=1).round(3)
lopo_piv["prevalencia_(ref.)"] = ""
prev_p = G.groupby("periodo").y.mean().round(3)
lopo_piv.loc["Prevalencia del periodo (referencia)", periodos] = prev_p.values
lopo_piv = lopo_piv.reset_index()

# ---------------------------------------------------------------- subgrupos (predicciones LOPO del mejor modelo)
def wilson(k, n, z=1.96):
    if n == 0: return (np.nan, np.nan)
    p = k / n; d = 1 + z ** 2 / n
    c = (p + z ** 2 / (2 * n)) / d; h = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / d
    return (max(0, c - h), min(1, c + h))

sp = pooled[mejor]
thr_p = umbral_recall(sp.values, G.y.values, RECALL_OBJETIVO)
thr_pb = umbral_recall(G.pct_inasistencia_d28.values, G.y.values, RECALL_OBJETIVO)
G["alerta_modelo"] = (sp >= thr_p).astype(int)
G["alerta_base"] = (G.pct_inasistencia_d28 >= thr_pb).astype(int)
G["nse_grupo"] = G.nivel_socioeconomico.map({"Q1": "Q1-Q2", "Q2": "Q1-Q2", "Q3": "Q3", "Q4": "Q4-Q5", "Q5": "Q4-Q5"}).fillna("Sin dato")
G["zona_grupo"] = G.zona_residencia.map(lambda v: "Sin dato" if pd.isna(v) else ("Machala" if v == "MACHALA" else "Otras zonas"))
sub_rows = []
for var, etiqueta in [("sexo", "Sexo"), ("nse_grupo", "Nivel socioeconómico"), ("jornada", "Jornada"), ("zona_grupo", "Zona de residencia")]:
    for v, g in G.groupby(var):
        k = int(g.y.sum()); tp = int(((g.y == 1) & (g.alerta_modelo == 1)).sum()); tpb = int(((g.y == 1) & (g.alerta_base == 1)).sum())
        lo, hi = wilson(tp, k)
        sub_rows.append(dict(variable=etiqueta, grupo=v, estudiantes=len(g), positivos=k,
            recall_modelo=round(tp / k, 3) if k else np.nan, IC95_recall=f"[{lo:.2f}; {hi:.2f}]",
            FNR_modelo=round(1 - tp / k, 3) if k else np.nan,
            recall_base=round(tpb / k, 3) if k else np.nan,
            tasa_alerta_modelo=round(g.alerta_modelo.mean(), 3), tasa_alerta_base=round(g.alerta_base.mean(), 3)))
sub = pd.DataFrame(sub_rows)

# ---------------------------------------------------------------- SHAP (mejor modelo, entrenado en train, sobre validación)
r = res[mejor]
best = r["best"]
Xt = best[:-1].transform(r["Xva"]); est = best[-1]
cols = list(r["Xva"].columns)
if isinstance(est, XGBClassifier) or isinstance(est, RandomForestClassifier):
    sv = shap.TreeExplainer(est).shap_values(Xt)
    if isinstance(sv, list): sv = sv[1]
    elif getattr(sv, "ndim", 2) == 3: sv = sv[:, :, 1]
else:
    sv = shap.LinearExplainer(est, best[:-1].transform(r["Xtr"])).shap_values(Xt)
imp_shap = pd.DataFrame({"variable": cols, "mean_abs_SHAP": np.abs(sv).mean(axis=0)}).sort_values("mean_abs_SHAP", ascending=False)

# ---------------------------------------------------------------- columnas excluidas por riesgo de fuga
excl = pd.DataFrame([
    ["dia_ultima_asistencia / fecha_ultima_asistencia", "Posterior al día 28 (describe cuándo se deja de asistir)"],
    ["pct_inasistencia_final / n_asig_reprobadas_*", "Definen la etiqueta; solo existen al cierre del periodo"],
    ["via_salida / situacion_periodo_siguiente / abandono_carrera_t1", "Desenlaces"],
    ["tiene_registro_asistencia", "Identifica a los retirados por construcción"],
    ["periodo / estado_periodo / fechas / duracion_semanas_periodo", "Identifican el periodo, no al estudiante"],
    ["beca_financiamiento", "Solo 3 positivos con beca parcial: no estimable"],
    ["carrera_codigo", "23 categorías: excede el techo de predictores"],
    ["irreversible_inasistencia_d28", "Todos sus casos son de modalidad dual: sin casos en el alcance presencial"],
], columns=["columna(s)", "motivo de exclusión"])

# ---------------------------------------------------------------- gráficos
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
AZ, GR, RJ, NA, VD = "#1F3864", "#8C8C8C", "#C0392B", "#E69F00", "#2E8B57"

# fig1 casos por periodo y vía
fig, ax = plt.subplots(figsize=(10, 5.5))
pv = pres.groupby(["periodo", "via_salida"]).size().unstack(fill_value=0)
orden = [("PERMANECE_APRUEBA", "Aprueba", "#7FA6D6"), ("PERMANECE_REPRUEBA_RENDIMIENTO", "Reprueba por rendimiento", NA),
         ("REPRUEBA_INASISTENCIAS", "Reprueba por inasistencias (clase positiva)", RJ), ("RETIRO_VOLUNTARIO", "Retiro voluntario", GR)]
bot = np.zeros(len(pv))
for col, lab, colr in orden:
    ax.bar(pv.index, pv[col], bottom=bot, label=lab, color=colr); bot += pv[col].values
for i, tot_ in enumerate(bot): ax.text(i, tot_ + 4, int(tot_), ha="center", fontsize=10)
ax.set_ylabel("Estudiantes (presencial)"); ax.set_title("Desenlace del primer periodo por cohorte (presencial, periodos cerrados)", loc="left", fontsize=12)
ax.legend(frameon=False, fontsize=9, loc="upper right"); plt.tight_layout(); plt.savefig(f"{OUT}/fig1_casos_por_periodo.png", dpi=200); plt.close()

# fig2 curvas PR en validación
fig, ax = plt.subplots(figsize=(7.5, 6))
pr, rc, _ = precision_recall_curve(yva, base_va); ax.plot(rc, pr, color=GR, lw=2.2, label=f"Línea base: inasistencia al día 28 (AUC-PR {average_precision_score(yva, base_va):.2f})")
for k, colr in [(mejorA, NA), (mejor, AZ)]:
    pr, rc, _ = precision_recall_curve(yva, res[k]["pva"])
    ax.plot(rc, pr, color=colr, lw=2.2, label=f"{k[0]} [{k[1]}] (AUC-PR {average_precision_score(yva, res[k]['pva']):.2f})")
ax.axhline(prevalencia, color=RJ, ls="--", lw=1); ax.text(0.02, prevalencia + 0.015, f"Prevalencia {prevalencia:.2f}", color=RJ, fontsize=9)
ax.set_xlabel("Sensibilidad (Recall)"); ax.set_ylabel("Precisión"); ax.set_ylim(0, 1.02); ax.set_xlim(0, 1)
ax.set_title("Curvas precisión-sensibilidad en la cohorte de validación (2025-2)", loc="left", fontsize=11)
ax.legend(frameon=False, fontsize=8.5, loc="upper right"); plt.tight_layout(); plt.savefig(f"{OUT}/fig2_curvas_PR_validacion.png", dpi=200); plt.close()

# fig3 AUC-PR con IC
fig, ax = plt.subplots(figsize=(9, 5.2))
t = tabla_val.copy(); t["lo"] = t.AUC_PR_IC95.str.extract(r"\[([\d.]+);")[0].astype(float); t["hi"] = t.AUC_PR_IC95.str.extract(r";\s*([\d.]+)\]")[0].astype(float)
t = t.iloc[::-1].reset_index(drop=True)
for i, rw in t.iterrows():
    colr = GR if rw.modelo.startswith("Línea") else AZ
    ax.plot([rw.lo, rw.hi], [i, i], color=colr, lw=2.5); ax.plot(rw.AUC_PR, i, "o", color=colr, ms=8)
ax.set_yticks(range(len(t))); ax.set_yticklabels(t.modelo); ax.axvline(prevalencia, color=RJ, ls="--", lw=1)
ax.text(prevalencia + 0.005, -0.7, f"Prevalencia {prevalencia:.2f}", color=RJ, fontsize=9)
ax.set_xlabel("AUC-PR en validación (IC 95 % por bootstrap)"); ax.set_title("Comparación de modelos frente a la línea base (cohorte 2025-2)", loc="left", fontsize=11)
plt.tight_layout(); plt.savefig(f"{OUT}/fig3_comparacion_modelos.png", dpi=200); plt.close()

# fig4 SHAP
fig, ax = plt.subplots(figsize=(8, 5.5))
top = imp_shap.head(10).iloc[::-1]
ax.barh(top.variable, top.mean_abs_SHAP, color=AZ); ax.set_xlabel("Importancia media |SHAP| (cohorte 2025-2)")
ax.set_title(f"Variables que más influyen en el riesgo: {mejor[0]} [{mejor[1]}]", loc="left", fontsize=11)
plt.tight_layout(); plt.savefig(f"{OUT}/fig4_shap_importancia.png", dpi=200); plt.close()

# fig5 subgrupos
fig, ax = plt.subplots(figsize=(9, 6))
s2 = sub[sub.positivos >= 10].reset_index(drop=True)
lab = [f"{r.variable}: {r.grupo} (n+={r.positivos})" for r in s2.itertuples()]
ax.barh(range(len(s2))[::-1], s2.FNR_modelo, color=[RJ if v > s2.FNR_modelo.mean() + 0.1 else AZ for v in s2.FNR_modelo])
ax.axvline(1 - RECALL_OBJETIVO, color=GR, ls="--", lw=1); ax.text(1 - RECALL_OBJETIVO + 0.005, len(s2) - 0.4, "FNR global ≈ 0,30", color=GR, fontsize=9)
ax.set_yticks(range(len(s2))[::-1]); ax.set_yticklabels(lab, fontsize=9); ax.set_xlabel("Tasa de falsos negativos (modelo)")
ax.set_title("Falsos negativos por subgrupo (predicciones por periodo omitido)", loc="left", fontsize=11)
plt.tight_layout(); plt.savefig(f"{OUT}/fig5_subgrupos_FNR.png", dpi=200); plt.close()

# ---------------------------------------------------------------- Excel de resultados
with pd.ExcelWriter(f"{OUT}/resultados_preliminares.xlsx", engine="openpyxl") as xw:
    criterios.to_excel(xw, sheet_name="0_criterios_declarados", index=False)
    alcance.to_excel(xw, sheet_name="1_alcance_y_conteos", index=False)
    perf.to_excel(xw, sheet_name="2_perfilado_por_periodo", index=False)
    tabla_val.to_excel(xw, sheet_name="3_validacion_2025-2", index=False)
    lopo_piv.to_excel(xw, sheet_name="4_AUC-PR_por_periodo", index=False)
    sub.to_excel(xw, sheet_name="5_subgrupos", index=False)
    imp_shap.to_excel(xw, sheet_name="6_SHAP", index=False)
    tabla_smote.to_excel(xw, sheet_name="7_pesos_vs_SMOTE", index=False)
    excl.to_excel(xw, sheet_name="8_columnas_excluidas", index=False)
    pd.DataFrame([[k[0], k[1], str(v["params"]), round(v["cv_ap"], 3), round(v["thr"], 4)] for k, v in res.items()] +
                 [["Línea base", "-", f"umbral inasistencia d28 >= {thr_base}", "-", thr_base]],
                 columns=["modelo", "conjunto", "hiperparámetros", "CV_AUC-PR_entrenamiento", "umbral_recall_0.70"]).to_excel(xw, sheet_name="9_hiperparametros_umbrales", index=False)
    for ws in xw.book.worksheets:
        for c in ws[1]:
            c.font = c.font.copy(bold=True)
        for col in ws.columns:
            w = max(len(str(c.value)) if c.value is not None else 0 for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(12, w + 2), 70)

resumen = dict(mejor=list(mejor), mejorA=list(mejorA), prevalencia_val=float(prevalencia), thr_base=float(thr_base))
json.dump(resumen, open(f"{OUT}/resumen.json", "w"), ensure_ascii=False)
print("LISTO", flush=True)
