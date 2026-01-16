"""
Label Studio Integration für manuelles Labeling & Trainingsdaten-Sammlung.

Workflow:
1. Quarantäne-Dokumente → Label Studio
2. Manuelles Labeling (Lieferant, Datum, Dokumenttyp)
3. Export → Training-Pipeline
4. Continual Learning
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)


@dataclass
class LabeledDocument:
    """Gelabeltes Dokument von Label Studio."""
    
    doc_id: str
    filename: str
    text: str
    
    # Labels
    supplier: Optional[str] = None
    date: Optional[str] = None
    document_type: Optional[str] = None
    
    # Metadaten
    labeled_by: Optional[str] = None
    labeled_at: Optional[str] = None
    confidence: float = 1.0  # Human-Label = 100% Confidence


class LabelStudioIntegration:
    """
    Integration mit Label Studio für Human-in-the-Loop Labeling.
    
    **Setup**:
    ```bash
    # Docker
    docker run -p 8080:8080 heartexlabs/label-studio:latest
    
    # Oder lokal
    pip install label-studio
    label-studio start
    ```
    
    **Nutzen**:
    - Web-UI für Annotations
    - Multi-User Support
    - Export zu ML-Formaten (JSON, CSV, COCO, etc.)
    - API für Automatisierung
    
    **Workflow**:
    1. `export_to_label_studio()`: Quarantäne-Dokumente exportieren
    2. Manuelles Labeling im Web-UI
    3. `import_from_label_studio()`: Gelabelte Daten importieren
    4. `prepare_training_data()`: Konvertiere zu ML-Format
    """
    
    def __init__(
        self,
        api_url: str = "http://localhost:8080",
        api_key: Optional[str] = None,
        project_id: Optional[int] = None
    ):
        """
        Args:
            api_url: Label Studio Server URL
            api_key: API-Key (optional, für Authentifizierung)
            project_id: Projekt-ID (optional)
        """
        self.api_url = api_url
        self.api_key = api_key
        self.project_id = project_id
        
        self._client = None
    
    def _get_client(self):
        """Lazy-Loading des Label Studio Clients."""
        if self._client is not None:
            return self._client
        
        try:
            from label_studio_sdk import Client
        except ImportError:
            raise ImportError(
                "label-studio-sdk ist nicht installiert. "
                "Installiere mit: pip install label-studio-sdk"
            )
        
        self._client = Client(url=self.api_url, api_key=self.api_key)
        
        _LOGGER.info(f"Label Studio Client initialisiert: {self.api_url}")
        
        return self._client
    
    def create_project(
        self,
        title: str = "Docaro Document Labeling",
        description: str = "Labeling für Lieferant, Datum, Dokumenttyp"
    ) -> int:
        """
        Erstellt neues Label Studio Projekt.
        
        Returns:
            Projekt-ID
        """
        client = self._get_client()
        
        # Label-Konfiguration (XML)
        label_config = '''
        <View>
          <Header value="Dokument-Labeling"/>
          
          <Text name="text" value="$text"/>
          
          <Header value="Lieferant"/>
          <TextArea name="supplier" toName="text" 
                    placeholder="Lieferantenname eingeben..." 
                    rows="1" maxSubmissions="1"/>
          
          <Header value="Datum (ISO: YYYY-MM-DD)"/>
          <TextArea name="date" toName="text" 
                    placeholder="YYYY-MM-DD" 
                    rows="1" maxSubmissions="1"/>
          
          <Header value="Dokumenttyp"/>
          <Choices name="document_type" toName="text" choice="single">
            <Choice value="Rechnung"/>
            <Choice value="Lieferschein"/>
            <Choice value="Bestellung"/>
            <Choice value="Gutschrift"/>
            <Choice value="Sonstige"/>
          </Choices>
          
          <Header value="Qualität"/>
          <Rating name="quality" toName="text" maxRating="5" 
                  icon="star" size="medium"/>
        </View>
        '''
        
        project = client.start_project(
            title=title,
            label_config=label_config,
            description=description
        )
        
        self.project_id = project.id
        
        _LOGGER.info(f"Projekt erstellt: {title} (ID: {project.id})")
        
        return project.id
    
    def export_to_label_studio(
        self,
        documents: List[Dict[str, Any]],
        batch_name: Optional[str] = None
    ) -> int:
        """
        Exportiert Dokumente zu Label Studio.
        
        Args:
            documents: Liste von Dicts mit {'filename', 'text', 'doc_id'}
            batch_name: Optional Batch-Name
        
        Returns:
            Anzahl exportierter Dokumente
        """
        if self.project_id is None:
            raise ValueError("Projekt-ID nicht gesetzt. Erstelle erst ein Projekt.")
        
        client = self._get_client()
        project = client.get_project(self.project_id)
        
        # Konvertiere zu Label Studio Format
        tasks = []
        
        for doc in documents:
            task = {
                'data': {
                    'text': doc['text'],
                    'filename': doc.get('filename', 'unknown'),
                    'doc_id': doc.get('doc_id', '')
                }
            }
            
            # Optional: Vor-Annotation (ML-Predictions als Vorschläge)
            if 'predictions' in doc:
                task['predictions'] = [{
                    'result': doc['predictions']
                }]
            
            tasks.append(task)
        
        # Upload Tasks
        project.import_tasks(tasks)
        
        _LOGGER.info(f"✅ {len(tasks)} Dokumente zu Label Studio exportiert")
        
        return len(tasks)
    
    def import_from_label_studio(
        self,
        export_format: str = "JSON"
    ) -> List[LabeledDocument]:
        """
        Importiert gelabelte Dokumente von Label Studio.
        
        Args:
            export_format: "JSON", "CSV", etc.
        
        Returns:
            Liste von LabeledDocuments
        """
        if self.project_id is None:
            raise ValueError("Projekt-ID nicht gesetzt")
        
        client = self._get_client()
        project = client.get_project(self.project_id)
        
        # Hole alle gelabelten Tasks
        tasks = project.get_labeled_tasks()
        
        labeled_docs = []
        
        for task in tasks:
            # Parse Annotations
            if not task.get('annotations'):
                continue
            
            # Neueste Annotation
            annotation = task['annotations'][-1]
            
            doc_id = task['data'].get('doc_id', '')
            filename = task['data'].get('filename', 'unknown')
            text = task['data'].get('text', '')
            
            # Extrahiere Labels
            supplier = None
            date = None
            document_type = None
            
            for result in annotation.get('result', []):
                if result['from_name'] == 'supplier':
                    supplier = result['value'].get('text', [None])[0]
                elif result['from_name'] == 'date':
                    date = result['value'].get('text', [None])[0]
                elif result['from_name'] == 'document_type':
                    choices = result['value'].get('choices', [])
                    document_type = choices[0] if choices else None
            
            labeled_docs.append(LabeledDocument(
                doc_id=doc_id,
                filename=filename,
                text=text,
                supplier=supplier,
                date=date,
                document_type=document_type,
                labeled_by=annotation.get('completed_by'),
                labeled_at=annotation.get('created_at')
            ))
        
        _LOGGER.info(f"✅ {len(labeled_docs)} gelabelte Dokumente importiert")
        
        return labeled_docs
    
    def prepare_training_data(
        self,
        labeled_docs: List[LabeledDocument],
        output_dir: Path
    ):
        """
        Konvertiert gelabelte Dokumente zu Training-Format.
        
        Args:
            labeled_docs: Liste von LabeledDocuments
            output_dir: Ausgabe-Verzeichnis (z.B. ml/data/labeled/)
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. JSON-Export (für alle Modelle)
        json_path = output_dir / "labeled_documents.json"
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(
                [
                    {
                        'doc_id': doc.doc_id,
                        'filename': doc.filename,
                        'text': doc.text,
                        'supplier': doc.supplier,
                        'date': doc.date,
                        'document_type': doc.document_type,
                        'labeled_at': doc.labeled_at
                    }
                    for doc in labeled_docs
                ],
                f,
                ensure_ascii=False,
                indent=2
            )
        
        _LOGGER.info(f"✅ Training-Daten gespeichert: {json_path}")
        
        # 2. CSV-Export (für einfache Analyse)
        import csv
        
        csv_path = output_dir / "labeled_documents.csv"
        
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'doc_id', 'filename', 'supplier', 'date', 'document_type', 'text_preview'
            ])
            writer.writeheader()
            
            for doc in labeled_docs:
                writer.writerow({
                    'doc_id': doc.doc_id,
                    'filename': doc.filename,
                    'supplier': doc.supplier or '',
                    'date': doc.date or '',
                    'document_type': doc.document_type or '',
                    'text_preview': doc.text[:100] + '...' if len(doc.text) > 100 else doc.text
                })
        
        _LOGGER.info(f"✅ CSV exportiert: {csv_path}")
        
        return json_path, csv_path


def quarantine_to_label_studio_workflow(quarantine_dir: Path):
    """
    Beispiel-Workflow: Quarantäne-Dokumente zu Label Studio exportieren.
    
    Args:
        quarantine_dir: Pfad zum Quarantäne-Ordner
    """
    _LOGGER.info("Starte Quarantäne → Label Studio Workflow")
    
    # 1. Sammle Quarantäne-Dokumente
    documents = []
    
    for pdf_path in quarantine_dir.glob("*.pdf"):
        # Extrahiere Text (vereinfacht)
        try:
            import pdfplumber
            
            with pdfplumber.open(pdf_path) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages[:3])
            
            documents.append({
                'doc_id': pdf_path.stem,
                'filename': pdf_path.name,
                'text': text[:5000]  # Limitiere Text-Länge
            })
        except Exception as e:
            _LOGGER.warning(f"Fehler bei {pdf_path.name}: {e}")
    
    _LOGGER.info(f"📄 {len(documents)} Quarantäne-Dokumente gesammelt")
    
    # 2. Erstelle Label Studio Projekt
    ls_integration = LabelStudioIntegration()
    
    try:
        project_id = ls_integration.create_project(
            title=f"Docaro Quarantine Batch {datetime.now().strftime('%Y-%m-%d')}"
        )
    except Exception as e:
        _LOGGER.error(f"Projekt-Erstellung fehlgeschlagen: {e}")
        return
    
    # 3. Exportiere zu Label Studio
    count = ls_integration.export_to_label_studio(documents)
    
    _LOGGER.info(f"✅ Workflow abgeschlossen: {count} Dokumente zu Label Studio exportiert")
    _LOGGER.info(f"   → Öffne: http://localhost:8080/projects/{project_id}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    from datetime import datetime
    from config import Config
    
    config = Config()
    quarantine_dir = config.QUARANTINE_DIR
    
    # Workflow ausführen
    quarantine_to_label_studio_workflow(quarantine_dir)
