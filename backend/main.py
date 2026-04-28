from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

# Ponto de entrada do servidor Flask.
# Importa create_app() de app/__init__.py, inicializa todas as extensões,
# migrations, blueprints e sobe o servidor na porta 8000.
# Executar: python main.py
