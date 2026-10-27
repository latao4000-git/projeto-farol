# Databricks notebook source
# MAGIC %md
# MAGIC # Noite 3 · Prompt 2 · O modelo: quais projetos vão estourar nos próximos 30 dias?
# MAGIC
# MAGIC A ordem deste notebook é a ordem que importa, e ela começa **antes** do `.fit()`:
# MAGIC
# MAGIC 1. **o baseline**: quanto vale o que a Vértice já faz (a regra de corte) e a melhor regra simples
# MAGIC 2. o treino, com corte no **tempo** (treina no passado, testa no futuro)
# MAGIC 3. a métrica de quem treina (AUC) e a métrica do dono (quantos estouros avisados, com quantos dias)
# MAGIC 4. MLflow e Unity Catalog: o modelo vira objeto de catálogo, com alias `@prod`
# MAGIC 5. **testes que interrompem a tarefa**: modelo ruim também "funciona", e por isso é testado
# MAGIC
# MAGIC **O que o modelo prevê:** o pior índice (o menor entre SPI e CPI) do projeto nas próximas 4 semanas.
# MAGIC A probabilidade de estouro sai daí: a chance de esse pior índice ficar abaixo de 0,9.
# MAGIC Prever o número, e não só sim/não, dá ao dono uma frase que ele entende:
# MAGIC *"o SPI deste projeto vai a 0,87 em 30 dias"*.

# COMMAND ----------

# MAGIC %md
# MAGIC **Primeiro, o MLflow novo.** O serverless vem com MLflow 2.11, que sobe o modelo para o Unity Catalog
# MAGIC com credencial direta no S3 — e o Free Edition **nega** (`s3:PutObject ... explicit deny`). A partir da
# MAGIC 2.21 o upload usa URL pré-assinada, que funciona. Medido em 18/10/2026.

# COMMAND ----------

# MAGIC %pip install -q -U "mlflow-skinny[databricks]>=2.21,<3"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "lakehouse_vertice")
catalog = dbutils.widgets.get("catalog")

MODELO = f"{catalog}.ml.modelo_estouro_30d"
SEMENTE = 42
CORTE = 0.9                      # a regra de corte da Torre: abaixo de 0,9 é atenção
CORTE_TREINO = "2026-03-06"      # treina com as semanas até aqui
INICIO_TESTE = "2026-04-03"      # testa a partir daqui: 4 semanas de folga = o horizonte do rótulo
TOP_K = 5                        # quantos projetos dá para olhar de perto por semana

import math
import mlflow
import numpy as np
import pandas as pd
from databricks.sdk import WorkspaceClient
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

FEATURES = [
    "spi", "cpi", "indice_min", "d_indice_min_4s", "pct_fisico", "pct_prazo",
    "d_spi_4s", "d_cpi_4s", "d_spi_8s", "d_cpi_8s", "semanas_cpi_caindo", "cpi_ultimas_4s", "spi_ultimas_4s",
    "ociosidade_4s", "pct_consultoria_4s", "pct_cloud_4s", "saidas_12s",
    "status_freeze_4s", "status_falta_sre_4s", "status_fornecedor_4s", "status_rotatividade_4s",
    "status_escopo_4s", "status_retrabalho_4s", "status_com_bloqueio_4s",
]

# DECIMAL vira objeto Decimal no pandas e quebra o registro do modelo
# ("Object of type Decimal is not JSON serializable"): tudo para double.
dados = spark.table(f"{catalog}.ml.features_projeto_semana").toPandas()
dados["semana"] = pd.to_datetime(dados["semana"])
dados[FEATURES] = dados[FEATURES].astype(float)

rotulados = dados[dados["alvo_pior_indice_30d"].notna()].copy()
elegiveis = rotulados[rotulados["elegivel"] == 1]
teste = elegiveis[elegiveis["semana"] >= INICIO_TESTE].copy()
y_teste = teste["estoura_30d"].astype(int)

print(f"{len(dados)} projetos×semana · {len(elegiveis)} elegíveis com rótulo · taxa base {elegiveis['estoura_30d'].mean():.1%}")
print(f"teste: {len(teste)} linhas a partir de {INICIO_TESTE}, {y_teste.sum()} estouros")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · O baseline, antes de treinar qualquer coisa
# MAGIC
# MAGIC Três réguas, medidas no mesmo teste:
# MAGIC
# MAGIC - **a regra de corte que a Vértice usa hoje** (SPI ou CPI < 0,9): no conjunto elegível, ninguém está abaixo
# MAGIC   de 0,9 — por definição ela **não avisa nada antes**. Antecedência: zero.
# MAGIC - **a folga até o corte**: quem está mais perto de 0,9 estoura primeiro. Regra de bolso, de graça.
# MAGIC - **a tendência**: quem caiu mais nas últimas 4 semanas.
# MAGIC
# MAGIC Spoiler da noite: a folga até o corte é **boa**. A regra simples é forte, e o modelo só tem o direito
# MAGIC de existir se ganhar dela.

# COMMAND ----------

def auc(score):
    return float(roc_auc_score(y_teste, score))

baselines = {
    "regra de corte atual (< 0,9)": 0.5,
    "folga até o corte (quem está mais perto de 0,9)": auc(-teste["indice_min"]),
    "só o CPI": auc(-teste["cpi"]),
    "tendência das últimas 4 semanas": auc(-teste["d_indice_min_4s"].fillna(0)),
}
for regra, valor in sorted(baselines.items(), key=lambda kv: kv[1]):
    print(f"  AUC {valor:.4f}   {regra}")
melhor_baseline = baselines["folga até o corte (quem está mais perto de 0,9)"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · O treino
# MAGIC
# MAGIC `HistGradientBoostingRegressor` (e não XGBoost, que no serverless treina, registra e **não carrega de
# MAGIC volta**). Ele aprende **quanto o pior índice vai cair** nas próximas 4 semanas, a partir do que o projeto
# MAGIC mostra hoje. Treina com todos os projetos do passado — inclusive os que já estavam abaixo de 0,9, porque
# MAGIC eles também ensinam como um projeto afunda.
# MAGIC
# MAGIC Nada de imputar nulo: a árvore trata `NaN` nativamente (as primeiras semanas não têm tendência).

# COMMAND ----------

def treinar(base):
    m = HistGradientBoostingRegressor(random_state=SEMENTE, max_depth=3, learning_rate=0.05,
                                      max_iter=300, min_samples_leaf=20)
    m.fit(base[FEATURES], base["alvo_pior_indice_30d"] - base["indice_min"])
    return m

def pior_previsto(m, base):
    return base["indice_min"].to_numpy() + m.predict(base[FEATURES])

def probabilidade(pior, sigma):
    """P(pior índice < 0,9) supondo erro normal com o desvio medido no teste."""
    z = (CORTE - np.asarray(pior)) / sigma
    return 0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2)))

historico = rotulados[(rotulados["semana"] <= CORTE_TREINO) & (rotulados["pct_prazo"] > 0.15)]
modelo_teste = treinar(historico)

teste["pior_previsto"] = pior_previsto(modelo_teste, teste)
sigma = float(np.std(teste["alvo_pior_indice_30d"] - teste["pior_previsto"]))
teste["prob"] = probabilidade(teste["pior_previsto"], sigma)
auc_modelo = auc(teste["prob"])
erro_medio = float(np.mean(np.abs(teste["alvo_pior_indice_30d"] - teste["pior_previsto"])))

# o classificador "de prateleira", só para registro: prever sim/não direto perde para a regra simples
clf = HistGradientBoostingClassifier(random_state=SEMENTE, max_depth=3, learning_rate=0.05,
                                     max_iter=200, min_samples_leaf=20)
treino_clf = elegiveis[elegiveis["semana"] <= CORTE_TREINO]
clf.fit(treino_clf[FEATURES], treino_clf["estoura_30d"].astype(int))
auc_classificador = auc(clf.predict_proba(teste[FEATURES])[:, 1])

print(f"AUC do modelo (prevê o índice):       {auc_modelo:.4f}")
print(f"AUC do classificador sim/não:         {auc_classificador:.4f}")
print(f"AUC da melhor regra simples (folga):  {melhor_baseline:.4f}")
print(f"erro médio do índice previsto: {erro_medio:.4f}   desvio (sigma): {sigma:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · A métrica do dono: quantos estouros a Torre teria avisado, e com quantos dias
# MAGIC
# MAGIC AUC é métrica de quem treina. O dono pergunta outra coisa: *"dos projetos que estouraram depois de
# MAGIC abril, quantos apareceriam na lista dos 5 mais arriscados da semana, e quanto tempo antes?"*
# MAGIC
# MAGIC Um **estouro** é o projeto que vinha há 4 semanas com SPI e CPI acima de 0,9, cruza para baixo e
# MAGIC **fica** abaixo por 2 semanas seguidas (uma semana só é ruído do status de sexta). Contamos como avisado se
# MAGIC ele esteve no top 5 em alguma semana das 8 anteriores ao cruzamento. Só contam cruzamentos a partir de 4
# MAGIC semanas depois do início do teste: antes disso o modelo nem teve chance de avisar.

# COMMAND ----------

todas = dados.sort_values(["projeto_id", "semana"])
eventos = []
for pid, s in todas.groupby("projeto_id"):
    s = s.reset_index(drop=True)
    for i in range(4, len(s) - 1):
        quando = s.loc[i, "semana"]
        if quando < pd.Timestamp(INICIO_TESTE) + pd.Timedelta(days=28) or s.loc[i, "pct_prazo"] <= 0.15:
            continue
        vinha_bem = all(s.loc[i - k, "indice_min"] >= CORTE for k in range(1, 5))
        ficou_abaixo = s.loc[i, "indice_min"] < CORTE and s.loc[i + 1, "indice_min"] < CORTE
        if vinha_bem and ficou_abaixo:
            eventos.append((pid, quando))
            break

teste["rank_modelo"] = teste.groupby("semana")["prob"].rank(ascending=False, method="first")
avisados, antecedencias = [], []
for pid, quando in eventos:
    janela = teste[(teste["projeto_id"] == pid) & (teste["semana"] < quando)
                   & (teste["semana"] >= quando - pd.Timedelta(days=56)) & (teste["rank_modelo"] <= TOP_K)]
    if len(janela):
        avisados.append(pid)
        antecedencias.append((quando - janela["semana"].min()).days)

antecedencia_media = float(np.mean(antecedencias)) if antecedencias else 0.0
estouro_avisado = spark.sql(f"""
    SELECT COALESCE(SUM(estouro_previsto), 0) AS v FROM {catalog}.gold.projeto_situacao_atual
    WHERE status = 'em_andamento' AND projeto_id IN ({",".join(f"'{p}'" for p in avisados) or "''"})""").first()["v"]
estouro_avisado = float(estouro_avisado)

print(f"estouros no teste: {len(eventos)}  →  {[p for p, _ in eventos]}")
print(f"avisados no top {TOP_K}: {len(avisados)} de {len(eventos)}, em média {antecedencia_media:.0f} dias antes")
print(f"a regra de corte atual avisa 0 de {len(eventos)} antes: ela só acende quando cruza")
print(f"estouro previsto hoje desses projetos: R$ {estouro_avisado / 1e6:.2f} mi")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · O que o modelo olhou
# MAGIC
# MAGIC Importância por **permutação**: embaralha uma coluna por vez e mede quanto o erro piora.

# COMMAND ----------

perm = permutation_importance(modelo_teste, teste[FEATURES],
                              teste["alvo_pior_indice_30d"] - teste["indice_min"],
                              n_repeats=5, random_state=SEMENTE, scoring="neg_mean_absolute_error")
importancia = (pd.DataFrame({"feature": FEATURES, "peso": perm.importances_mean})
               .sort_values("peso", ascending=False).reset_index(drop=True))
print(importancia.head(8).to_string(index=False))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Os testes que interrompem a tarefa
# MAGIC
# MAGIC Dado errado quebra. Modelo ruim **funciona**: devolve probabilidade para todo mundo, sem erro nenhum.
# MAGIC Por isso ele passa pelos mesmos testes que o dado — e os testes rodam **antes** de registrar.

# COMMAND ----------

assert auc_modelo >= 0.75, f"AUC {auc_modelo:.4f} abaixo do mínimo de 0,75 do PRD"
assert auc_modelo < 0.98, (f"AUC {auc_modelo:.4f} é bom DEMAIS: em previsão de projeto isso é vazamento — "
                            "alguma feature enxergou o futuro")
assert auc_modelo >= melhor_baseline, (f"o modelo ({auc_modelo:.4f}) perde da regra simples da folga "
                                       f"({melhor_baseline:.4f}). Então use a regra, não o modelo.")
assert len(avisados) >= 0.7 * len(eventos), f"só {len(avisados)} de {len(eventos)} estouros avisados"
print("os quatro testes passaram")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6 · MLflow e Unity Catalog
# MAGIC
# MAGIC Validado no passado, o modelo de produção é **retreinado com tudo** que tem rótulo (até 18/09/2026).
# MAGIC `set_experiment` não cria a pasta pai (o erro é `BAD_REQUEST: For input string: "None"`), por isso o
# MAGIC `mkdirs` vem antes. No serverless o MLflow é 2.x: `log_model(..., artifact_path=...)`.

# COMMAND ----------

modelo = treinar(rotulados[rotulados["pct_prazo"] > 0.15])

usuario = WorkspaceClient().current_user.me().user_name
PASTA = f"/Users/{usuario}/vertice"
WorkspaceClient().workspace.mkdirs(PASTA)
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(f"{PASTA}/modelo_estouro_30d")

with mlflow.start_run(run_name="modelo_estouro_30d") as run:
    mlflow.log_params({"algoritmo": "HistGradientBoostingRegressor", "alvo": "pior índice em 4 semanas",
                       "corte_treino": CORTE_TREINO, "inicio_teste": INICIO_TESTE, "features": len(FEATURES),
                       "random_state": SEMENTE, "top_k": TOP_K})
    mlflow.log_metrics({"auc": auc_modelo, "auc_classificador": auc_classificador,
                        "auc_baseline_folga": melhor_baseline, "erro_medio_indice": erro_medio,
                        "sigma": sigma, "estouros_teste": len(eventos), "estouros_avisados": len(avisados),
                        "antecedencia_media_dias": antecedencia_media})
    info = mlflow.sklearn.log_model(modelo, artifact_path="modelo", registered_model_name=MODELO,
                                    input_example=historico[FEATURES].head(3))

versao = info.registered_model_version
mlflow.MlflowClient().set_registered_model_alias(MODELO, "prod", versao)
print(f"{MODELO} versão {versao} registrada com o alias @prod")

# COMMAND ----------

# A tarefa de score lê daqui o sigma e a versão: é o "manual" do modelo, em tabela.
metricas = pd.DataFrame([{
    "modelo": MODELO, "versao": int(versao), "treinado_em": pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None),
    "auc": auc_modelo, "auc_classificador": auc_classificador, "auc_baseline_folga": melhor_baseline,
    "auc_regra_atual": 0.5, "auc_baseline_cpi": baselines["só o CPI"],
    "auc_baseline_tendencia": baselines["tendência das últimas 4 semanas"],
    "linhas_teste": len(teste), "estouros_linhas_teste": int(y_teste.sum()),
    "erro_medio_indice": erro_medio, "sigma": sigma, "estouros_teste": len(eventos),
    "estouros_avisados": len(avisados), "antecedencia_media_dias": antecedencia_media,
    "estouro_previsto_avisado": estouro_avisado, "top_k": TOP_K,
    "projetos_avisados": ", ".join(avisados), "projetos_estouraram": ", ".join(p for p, _ in eventos),
    "feature_principal": importancia.iloc[0]["feature"], "corte_treino": CORTE_TREINO,
}])
(spark.createDataFrame(metricas).write.mode("overwrite").option("overwriteSchema", "true")
 .saveAsTable(f"{catalog}.ml.modelo_metricas"))
spark.sql(f"COMMENT ON TABLE {catalog}.ml.modelo_metricas IS "
          "'Noite 3: métricas da última versão do modelo de estouro em 30 dias (AUC, baseline, estouros avisados, sigma).'")
display(spark.table(f"{catalog}.ml.modelo_metricas"))
