import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from dotenv import load_dotenv
load_dotenv()
from server.api.routes import router, APP_VERSION

logger = logging.getLogger('rita')


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Précharge Florence au démarrage (sinon la 1re analyse paie le chargement du modèle).
    # RITA_PRELOAD=0 pour désactiver ; un échec n'empêche pas l'API de démarrer.
    # V2.14 : le préchargement ne concerne que le moteur local — inutile si
    # VISION_ENGINE=mistral (aucun modèle à charger, l'appel se fera à la demande).
    if os.getenv('RITA_PRELOAD', '1') != '0' and os.getenv('VISION_ENGINE', 'florence') != 'mistral':
        try:
            from server.vision.florence import load_model
            load_model()
        except Exception:
            logger.warning('Préchargement de Florence impossible : chargement à la première analyse.', exc_info=True)
    yield


app = FastAPI(title='RITA Vision API', version=APP_VERSION + '-moteurs-interchangeables', lifespan=lifespan)
app.include_router(router)
