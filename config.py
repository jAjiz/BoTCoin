from dotenv import load_dotenv
import os

# Cargar las variables del archivo .env
load_dotenv()

KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET")
