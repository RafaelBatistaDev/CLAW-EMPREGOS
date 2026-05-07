#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash
import job_hunter

app = Flask(__name__)
app.secret_key = 'supersecretkey'

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config_vagas.json"
DATA_DIR = BASE_DIR / "vagas"

@app.route('/')
def index():
    vagas_files = list(DATA_DIR.glob("vagas_*.json"))
    if not vagas_files: return render_template('index.html', categorias={})
    latest_file = max(vagas_files, key=lambda f: f.stat().st_mtime)
    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        vagas = data.get('vagas', [])
    except: vagas = []
    
    categorias = {}
    for vaga in vagas:
        cat = vaga.get('categoria', 'Outros')
        if cat not in categorias: categorias[cat] = []
        categorias[cat].append(vaga)
    return render_template('index.html', categorias=categorias)

@app.route('/config', methods=['GET', 'POST'])
def config():
    if request.method == 'POST':
        config_data = {
            "keywords": request.form.get('keywords', '').split('\n'),
            "localizacao": request.form.get('localizacao', ''),
            "max_vagas_por_plataforma": int(request.form.get('max_vagas', 20)),
            "delay_entre_requisicoes": float(request.form.get('delay', 2.5)),
            "plataformas": request.form.getlist('plataformas')
        }
        # Limpa keywords vazias
        config_data['keywords'] = [k.strip() for k in config_data['keywords'] if k.strip()]
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        flash("Configuração salva!")
        return redirect(url_for('config'))

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except: config = {}
    return render_template('config.html', config=config)

@app.route('/run')
def run():
    try:
        job_hunter.bootstrap()
        cfg = job_hunter.carregar_config(CONFIG_FILE)
        vagas = job_hunter.executar_busca(cfg)
        vagas = job_hunter.categorize_vagas(vagas, cfg["keywords"])
        job_hunter.salvar_json(vagas, job_hunter.JSON_OUT)
        flash(f"Coleta concluída! {len(vagas)} vagas.")
    except Exception as e:
        flash(f"Erro: {e}")
    return redirect(url_for('index'))

@app.route('/clear')
def clear():
    try:
        if DATA_DIR.exists():
            for f in DATA_DIR.glob("vagas_*.json"):
                f.unlink()
            flash("✅ Histórico de vagas limpo com sucesso!")
    except Exception as e:
        flash(f"Erro ao limpar: {e}")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
