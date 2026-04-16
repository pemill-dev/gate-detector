#!/usr/bin/env python3
"""
Sistema de Detecção de Carros e Abertura Automática de Portão
Monitora câmera DVR Intelbras via ONVIF e detecta carros com YOLOv8
"""

import logging
import time
import json
import requests
import cv2
import numpy as np
import os
import warnings
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
from threading import Thread, Lock
import traceback

# Suprimir avisos do PyTorch/NNPACK ANTES de importar YOLO
os.environ['TORCH_WARN_ONCE'] = '0'
os.environ['PYTHONWARNINGS'] = 'ignore'
warnings.filterwarnings('ignore')

# Suprimir logs de debug do PyTorch
logging.getLogger('torch').setLevel(logging.ERROR)
logging.getLogger('torchvision').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)

# Importar YOLO após suprimir avisos
from ultralytics import YOLO

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/gate_detector.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Suprimir avisos de bibliotecas externas
logging.getLogger('onvif').setLevel(logging.ERROR)

# Criar diretório de logs se não existir
Path('/app/logs').mkdir(parents=True, exist_ok=True)


class GateDetectionSystem:
    """Sistema de detecção de carros e abertura de portão"""
    
    def __init__(
        self,
        dvr_host: str,
        dvr_port: int,
        dvr_user: str,
        dvr_pass: str,
        camera_index: int,
        gate_api_url: str,
        gate_cooldown_seconds: int = 60,
        confidence_threshold: float = 0.5,
        car_classes: list = None
    ):
        """
        Inicializa o sistema de detecção
        
        Args:
            dvr_host: IP da DVR
            dvr_port: Porta da DVR
            dvr_user: Usuário da DVR
            dvr_pass: Senha da DVR
            camera_index: Índice da câmera (1-based)
            gate_api_url: URL da API para abrir o portão
            gate_cooldown_seconds: Tempo mínimo entre aberturas
            confidence_threshold: Confiança mínima para detecção
            car_classes: Classes de objetos a detectar (ex: ['car', 'truck'])
        """
        self.dvr_host = dvr_host
        self.dvr_port = dvr_port
        self.dvr_user = dvr_user
        self.dvr_pass = dvr_pass
        self.camera_index = camera_index
        self.gate_api_url = gate_api_url
        self.gate_cooldown_seconds = gate_cooldown_seconds
        self.confidence_threshold = confidence_threshold
        self.car_classes = car_classes or ['car', 'truck', 'bus', 'motorcycle']
        
        # Estado do sistema
        self.lock = Lock()
        self.is_running = False
        self.gate_last_opened = None
        self.is_gate_open = False
        self.stream_url = None
        self.cap = None
        self.model = None
        
        logger.info(f"Sistema inicializado: DVR={dvr_host}:{dvr_port}, Câmera={camera_index}")
    
    def get_stream_url_from_onvif(self) -> Optional[str]:
        """
        Obtém a URL de stream RTSP da câmera via ONVIF
        
        Returns:
            URL RTSP ou None se falhar
        """
        try:
            logger.info("Conectando à DVR via ONVIF...")
            from onvif import ONVIFCamera
            
            # Conectar à DVR
            mycam = ONVIFCamera(
                self.dvr_host,
                self.dvr_port,
                self.dvr_user,
                self.dvr_pass
            )
            
            # Obter perfis de mídia
            media_service = mycam.create_media_service()
            profiles = media_service.GetProfiles()
            
            if not profiles:
                logger.error("Nenhum perfil de mídia encontrado")
                return None
            
            # Usar o perfil correspondente à câmera
            # Nota: Pode ser necessário ajustar a lógica conforme a DVR
            profile = profiles[self.camera_index - 1] if len(profiles) >= self.camera_index else profiles[0]
            
            # Obter URL de stream
            stream_uri = media_service.GetStreamUri({'ProfileToken': profile.token})
            stream_url = stream_uri.Uri
            
            logger.info(f"URL de stream obtida: {stream_url}")
            return stream_url
            
        except Exception as e:
            logger.error(f"Erro ao obter stream via ONVIF: {e}")
            logger.debug(traceback.format_exc())
            return None
    
    def get_stream_url_fallback(self) -> str:
        """
        URL de fallback caso ONVIF falhe
        Usa URL RTSP correta para Intelbras iMHDX
        """
        # URL RTSP correta para Intelbras: rtsp://user:pass@host/cam/realmonitor?channel=X&subtype=0
        url = f"rtsp://{self.dvr_user}:{self.dvr_pass}@{self.dvr_host}/cam/realmonitor?channel={self.camera_index}&subtype=0"
        logger.info(f"Usando URL de fallback: {url}")
        return url
    
    def initialize_stream(self) -> bool:
        """
        Inicializa a conexão com o stream de vídeo
        
        Returns:
            True se bem-sucedido, False caso contrário
        """
        try:
            # Tentar obter URL via ONVIF
            self.stream_url = self.get_stream_url_from_onvif()
            
            # Se falhar, usar fallback
            if not self.stream_url:
                self.stream_url = self.get_stream_url_fallback()
            
            # Conectar ao stream
            logger.info(f"Conectando ao stream: {self.stream_url}")
            self.cap = cv2.VideoCapture(self.stream_url)
            
            if not self.cap.isOpened():
                logger.error("Falha ao abrir stream de vídeo")
                return False
            
            logger.info("Stream de vídeo inicializado com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao inicializar stream: {e}")
            logger.debug(traceback.format_exc())
            return False
    
    def initialize_model(self) -> bool:
        """
        Carrega o modelo YOLOv8 para detecção
        
        Returns:
            True se bem-sucedido, False caso contrário
        """
        try:
            logger.info("Carregando modelo YOLOv8...")
            # Usar modelo nano para melhor performance
            # Suprimir avisos do PyTorch durante carregamento
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                self.model = YOLO('yolov8n.pt')
            logger.info("Modelo YOLOv8 carregado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao carregar modelo: {e}")
            logger.debug(traceback.format_exc())
            return False
    
    def detect_cars_in_frame(self, frame: np.ndarray) -> tuple:
        """
        Detecta carros em um frame usando YOLOv8
        
        Args:
            frame: Frame de vídeo (numpy array)
            
        Returns:
            Tupla (tem_carro, detecções)
        """
        try:
            if self.model is None:
                return False, []
            
            # Executar detecção
            results = self.model(frame, verbose=False, conf=self.confidence_threshold)
            
            detections = []
            has_car = False
            
            for result in results:
                if result.boxes is not None:
                    for box in result.boxes:
                        # Obter classe e confiança
                        class_id = int(box.cls[0])
                        confidence = float(box.conf[0])
                        class_name = result.names[class_id]
                        
                        # Verificar se é um veículo de interesse
                        if class_name.lower() in self.car_classes:
                            has_car = True
                            detections.append({
                                'class': class_name,
                                'confidence': confidence,
                                'box': box.xyxy[0].tolist()
                            })
            
            return has_car, detections
            
        except Exception as e:
            logger.error(f"Erro ao detectar carros: {e}")
            logger.debug(traceback.format_exc())
            return False, []
    
    def send_gate_open_request(self) -> bool:
        """
        Envia requisição POST para abrir o portão
        
        Returns:
            True se bem-sucedido, False caso contrário
        """
        try:
            logger.info(f"Enviando requisição para abrir portão: {self.gate_api_url}")
            
            payload = {"action": "open"}
            response = requests.post(
                self.gate_api_url,
                json=payload,
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info(f"Portão aberto com sucesso. Status: {response.status_code}")
                return True
            else:
                logger.warning(f"Resposta inesperada: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error("Timeout ao enviar requisição para abrir portão")
            return False
        except Exception as e:
            logger.error(f"Erro ao enviar requisição: {e}")
            logger.debug(traceback.format_exc())
            return False
    
    def check_and_open_gate(self, has_car: bool) -> None:
        """
        Verifica se deve abrir o portão baseado na detecção de carro
        
        Args:
            has_car: Se foi detectado um carro
        """
        with self.lock:
            current_time = datetime.now()
            
            # Se detectou carro e portão está fechado
            if has_car and not self.is_gate_open:
                # Verificar se passou o tempo de cooldown
                if self.gate_last_opened is None or \
                   (current_time - self.gate_last_opened).total_seconds() >= self.gate_cooldown_seconds:
                    
                    # Enviar requisição para abrir
                    if self.send_gate_open_request():
                        self.is_gate_open = True
                        self.gate_last_opened = current_time
                        logger.info(f"Portão aberto. Próxima abertura permitida em {self.gate_cooldown_seconds}s")
            
            # Se portão está aberto e passou o tempo de cooldown
            elif self.is_gate_open and self.gate_last_opened:
                if (current_time - self.gate_last_opened).total_seconds() >= self.gate_cooldown_seconds:
                    self.is_gate_open = False
                    logger.info("Portão marcado como fechado")
    
    def process_frame(self, frame: np.ndarray) -> None:
        """
        Processa um frame: detecta carros e abre portão se necessário
        
        Args:
            frame: Frame de vídeo
        """
        try:
            # Detectar carros
            has_car, detections = self.detect_cars_in_frame(frame)
            
            if has_car:
                logger.debug(f"Carros detectados: {len(detections)}")
            
            # Verificar e abrir portão se necessário
            self.check_and_open_gate(has_car)
            
        except Exception as e:
            logger.error(f"Erro ao processar frame: {e}")
            logger.debug(traceback.format_exc())
    
    def run(self) -> None:
        """
        Loop principal do sistema de detecção
        """
        try:
            logger.info("Iniciando sistema de detecção...")
            
            # Inicializar stream
            if not self.initialize_stream():
                logger.error("Falha ao inicializar stream")
                return
            
            # Inicializar modelo
            if not self.initialize_model():
                logger.error("Falha ao inicializar modelo")
                self.cleanup()
                return
            
            self.is_running = True
            logger.info("Sistema pronto. Monitorando câmera...")
            
            # Loop de processamento
            frame_count = 0
            while self.is_running:
                try:
                    ret, frame = self.cap.read()
                    
                    if not ret:
                        logger.warning("Falha ao ler frame do stream")
                        # Tentar reconectar
                        if not self.initialize_stream():
                            logger.error("Falha ao reconectar ao stream")
                            break
                        continue
                    
                    # Processar frame a cada N frames para melhor performance
                    frame_count += 1
                    if frame_count % 5 == 0:  # Processar a cada 5 frames
                        self.process_frame(frame)
                    
                except KeyboardInterrupt:
                    logger.info("Interrupção do usuário")
                    break
                except Exception as e:
                    logger.error(f"Erro no loop principal: {e}")
                    logger.debug(traceback.format_exc())
                    time.sleep(1)
        
        except Exception as e:
            logger.error(f"Erro fatal: {e}")
            logger.debug(traceback.format_exc())
        
        finally:
            self.cleanup()
    
    def cleanup(self) -> None:
        """
        Limpa recursos
        """
        logger.info("Limpando recursos...")
        self.is_running = False
        
        if self.cap:
            self.cap.release()
        
        logger.info("Sistema encerrado")


def main():
    """Função principal"""
    import os
    
    # Obter configurações das variáveis de ambiente
    dvr_host = os.getenv('DVR_HOST', '192.168.0.21')
    dvr_port = int(os.getenv('DVR_PORT', '80'))
    dvr_user = os.getenv('DVR_USER', 'manus')
    dvr_pass = os.getenv('DVR_PASS', 'Teste123')
    camera_index = int(os.getenv('CAMERA_INDEX', '2'))
    gate_api_url = os.getenv('GATE_API_URL', 'http://api-v2.pemill.com.br/open/dor/2')
    gate_cooldown_seconds = int(os.getenv('GATE_COOLDOWN_SECONDS', '60'))
    confidence_threshold = float(os.getenv('CONFIDENCE_THRESHOLD', '0.5'))
    
    # Criar e executar sistema
    system = GateDetectionSystem(
        dvr_host=dvr_host,
        dvr_port=dvr_port,
        dvr_user=dvr_user,
        dvr_pass=dvr_pass,
        camera_index=camera_index,
        gate_api_url=gate_api_url,
        gate_cooldown_seconds=gate_cooldown_seconds,
        confidence_threshold=confidence_threshold
    )
    
    system.run()


if __name__ == '__main__':
    main()
