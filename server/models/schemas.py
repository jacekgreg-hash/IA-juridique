from typing import Any
from pydantic import BaseModel, Field


class ProductIdentification(BaseModel):
    objet: str | None = None
    designation_commerciale: str | None = None
    marque: str | None = None
    modele: str | None = None
    reference: str | None = None
    modele_candidate: str | None = None
    reference_candidate: str | None = None
    modele_statut: str = 'inconnu'
    reference_statut: str = 'inconnu'
    modele_confiance_moteur: float = 0.0
    reference_confiance_moteur: float = 0.0
    texte_visible: list[str] = Field(default_factory=list)
    caracteristiques: list[str] = Field(default_factory=list)
    matiere_composition: list[str] = Field(default_factory=list)
    usage_fonction: str | None = None
    origine_visible: str | None = None
    informations_visuelles_certaines: list[str] = Field(default_factory=list)
    informations_a_verifier: list[str] = Field(default_factory=list)
    identification_confiance: float = 0.0
    reference_confiance: float = 0.0


class Evidence(BaseModel):
    source: str
    field: str
    value: str
    confidence: float = 0.0
    role: str = 'support'


class AnalysisResponse(BaseModel):
    produit: ProductIdentification
    ocr_text: list[str] = Field(default_factory=list)
    preuves: list[Evidence] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    informations_manquantes: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
