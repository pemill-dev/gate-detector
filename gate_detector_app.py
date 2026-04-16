#!/usr/bin/env python3
"""
Sistema de Detecção de Carros e Abertura Automática de Portão
Monitora câmera DVR Intelbras via ONVIF e detecta carros com YOLOv8
Aguarda veículo parado por tempo configurável antes de abrir portão
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
import base64
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List
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
        car_classes: list = None,
        rocket_chat_webhook: str = None,
        car_stationary_seconds: int = 3,
        roi_exclude: Tuple[int, int, int, int] = None
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
            rocket_chat_webhook: URL do webhook do Rocket.Chat
            car_stationary_seconds: Tempo que o carro deve ficar parado (segundos)
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
        self.rocket_chat_webhook = rocket_chat_webhook
        self.car_stationary_seconds = car_stationary_seconds
        self.roi_exclude = roi_exclude  # (x1, y1, x2, y2) para excluir detecções
        
        # Estado do sistema
        self.lock = Lock()
        self.is_running = False
        self.gate_last_opened = None
        self.is_gate_open = False
        self.stream_url = None
        self.cap = None
        self.model = None
        self.last_frame = None
        
        # Rastreamento de veículos parados
        self.car_detection_start_time = None
        self.last_car_position = None
        self.position_stability_count = 0
        
        logger.info(f"Sistema inicializado: DVR={dvr_host}:{dvr_port}, Câmera={camera_index}, Tempo parado={car_stationary_seconds}s")
    
    def get_stream_url_from_onvif(self) -> Optional[str]:
        """
        Obtem a URL de stream RTSP da camera via ONVIF
        Tenta multiplas portas comuns em DVRs Intelbras
        
        Returns:
            URL RTSP ou None se falhar
        """
        from onvif import ONVIFCamera
        
        # Portas comuns para ONVIF em DVRs Intelbras
        portas_onvif = [self.dvr_port, 8899, 80, 8080]
        
        for porta in portas_onvif:
            try:
                logger.info(f"Tentando ONVIF na porta {porta}...")
                
                # Conectar a DVR com wsdl_dir=None para evitar erro de HTTPS
                # Usar wsdl_dir=None desabilita cache de WSDL que pode causar problemas
                mycam = ONVIFCamera(
                    self.dvr_host,
                    porta,
                    self.dvr_user,
                    self.dvr_pass,
                    wsdl_dir=None
                )
                
                # Obter perfis de midia
                media_service = mycam.create_media_service()
                profiles = media_service.GetProfiles()
                
                if not profiles:
                    logger.debug(f"Nenhum perfil de midia encontrado na porta {porta}")
                    continue
                
                # Usar o perfil correspondente a camera
                profile = profiles[self.camera_index - 1] if len(profiles) >= self.camera_index else profiles[0]
                
                # Obter URL de stream
                stream_uri = media_service.GetStreamUri({'ProfileToken': profile.token})
                stream_url = stream_uri.Uri
                
                logger.info(f"URL de stream obtida via ONVIF (porta {porta}): {stream_url}")
                return stream_url
                
            except Exception as e:
                logger.debug(f"ONVIF falhou na porta {porta}: {str(e)[:100]}")
                continue
        
        logger.warning("Nao foi possivel obter stream via ONVIF em nenhuma porta")
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
    
    def detect_cars_in_frame(self, frame: np.ndarray) -> Tuple[bool, List]:
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
                            # Verificar se está na ROI de exclusão
                            if self._is_in_excluded_roi(box.xyxy[0].tolist()):
                                logger.debug(f"Detecção ignorada - está na área de exclusão")
                                continue
                            
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
    
    def send_rocket_chat_notification(self, frame: np.ndarray) -> bool:
        """
        Envia notificação com screenshot para Rocket.Chat
        
        Args:
            frame: Frame de vídeo para capturar
            
        Returns:
            True se bem-sucedido, False caso contrário
        """
        if not self.rocket_chat_webhook:
            return False
        
        try:
            # Codificar frame em PNG
            success, buffer = cv2.imencode('.png', frame)
            if not success:
                logger.error("Falha ao codificar frame em PNG")
                return False
            
            # Converter para Base64
            img_base64 = base64.b64encode(buffer).decode('utf-8')
            
            # Criar payload para Rocket.Chat
            timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            payload = {
                "text": f"🚗 Portão Aberto - {timestamp}",
                "attachments": [
                    {
                        "text": "Captura da câmera no momento da detecção",
                        "image_url": f"data:image/png;base64,{img_base64}",
                        "color": "#764FA5"
                    }
                ]
            }
            
            # Enviar para Rocket.Chat
            response = requests.post(
                self.rocket_chat_webhook,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Notificação enviada para Rocket.Chat com sucesso")
                return True
            else:
                logger.warning(f"Falha ao enviar para Rocket.Chat: {response.status_code}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error("Timeout ao enviar notificação para Rocket.Chat")
            return False
        except Exception as e:
            logger.error(f"Erro ao enviar notificação para Rocket.Chat: {e}")
            logger.debug(traceback.format_exc())
            return False
    
    def _calculate_detection_center(self, detections: List) -> Tuple[float, float]:
        """
        Calcula o centro da detecção (média das caixas)
        
        Args:
            detections: Lista de detecções
            
        Returns:
            Tupla (x_center, y_center)
        """
        if not detections:
            return (0, 0)
        
        total_x = 0
        total_y = 0
        
        for detection in detections:
            box = detection['box']  # [x1, y1, x2, y2]
            x_center = (box[0] + box[2]) / 2
            y_center = (box[1] + box[3]) / 2
            total_x += x_center
            total_y += y_center
        
        avg_x = total_x / len(detections)
        avg_y = total_y / len(detections)
        
        return (avg_x, avg_y)
    
    def _is_position_stable(self, last_pos: Tuple[float, float], current_pos: Tuple[float, float], threshold: float = 50.0) -> bool:
        """
        Verifica se a posição do carro é estável (não se moveu muito)
        
        Args:
            last_pos: Posição anterior
            current_pos: Posição atual
            threshold: Distância máxima em pixels para considerar estável
            
        Returns:
            True se posição é estável, False caso contrário
        """
        if last_pos is None:
            return True
        
        # Calcular distância euclidiana
        distance = np.sqrt((current_pos[0] - last_pos[0])**2 + (current_pos[1] - last_pos[1])**2)
        
        return distance < threshold
    
    def _is_in_excluded_roi(self, box: List[float]) -> bool:
        """
        Verifica se a deteccao esta na area de exclusao (ROI)
        
        Args:
            box: Caixa de deteccao [x1, y1, x2, y2]
            
        Returns:
            True se esta na area de exclusao, False caso contrario
        """
        if self.roi_exclude is None:
            return False
        
        # Extrair coordenadas da caixa
        x1, y1, x2, y2 = box
        roi_x1, roi_y1, roi_x2, roi_y2 = self.roi_exclude
        
        # Verificar se a caixa se sobrepoe com a ROI de exclusao
        # Se houver sobreposicao, retorna True (deve ser excluida)
        if x1 < roi_x2 and x2 > roi_x1 and y1 < roi_y2 and y2 > roi_y1:
            return True
        
        return False
    
    def check_and_open_gate(self, has_car: bool, detections: List = None) -> None:
        """
        Verifica se deve abrir o portão baseado na detecção de carro parado
        
        Args:
            has_car: Se foi detectado um carro
            detections: Lista de detecções com posições dos carros
        """
        with self.lock:
            current_time = datetime.now()
            
            # Se detectou carro
            if has_car and detections:
                # Calcular posição média dos carros detectados
                current_position = self._calculate_detection_center(detections)
                
                # Se é a primeira detecção de carro
                if self.car_detection_start_time is None:
                    self.car_detection_start_time = current_time
                    self.last_car_position = current_position
                    self.position_stability_count = 0
                    logger.debug("Carro detectado - iniciando contagem de tempo")
                
                # Se carro mantém posição similar (parado)
                elif self._is_position_stable(self.last_car_position, current_position):
                    self.position_stability_count += 1
                    elapsed_time = (current_time - self.car_detection_start_time).total_seconds()
                    
                    # Se carro ficou parado por tempo suficiente
                    if elapsed_time >= self.car_stationary_seconds and not self.is_gate_open:
                        # Verificar se passou o tempo de cooldown
                        if self.gate_last_opened is None or \
                           (current_time - self.gate_last_opened).total_seconds() >= self.gate_cooldown_seconds:
                            
                            logger.info(f"Carro parado por {elapsed_time:.1f}s - Abrindo portão")
                            
                            # Enviar requisição para abrir
                            if self.send_gate_open_request():
                                self.is_gate_open = True
                                self.gate_last_opened = current_time
                                logger.info(f"Portão aberto. Próxima abertura permitida em {self.gate_cooldown_seconds}s")
                                
                                # Enviar notificação para Rocket.Chat com screenshot
                                if self.last_frame is not None:
                                    self.send_rocket_chat_notification(self.last_frame)
                                
                                # Resetar rastreamento
                                self.car_detection_start_time = None
                                self.last_car_position = None
                                self.position_stability_count = 0
                else:
                    # Posição mudou - resetar contagem
                    self.last_car_position = current_position
                    self.position_stability_count = 0
                    logger.debug("Carro em movimento - resetando contagem")
            
            # Se não detectou carro
            else:
                # Resetar rastreamento
                if self.car_detection_start_time is not None:
                    logger.debug("Carro desapareceu - resetando rastreamento")
                    self.car_detection_start_time = None
                    self.last_car_position = None
                    self.position_stability_count = 0
            
            # Se portão está aberto e passou o tempo de cooldown
            if self.is_gate_open and self.gate_last_opened:
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
            # Armazenar frame atual para possível envio ao Rocket.Chat
            self.last_frame = frame.copy()
            
            # Detectar carros
            has_car, detections = self.detect_cars_in_frame(frame)
            
            if has_car:
                logger.debug(f"Carros detectados: {len(detections)}")
            
            # Verificar e abrir portão se necessário (com detecção de parada)
            self.check_and_open_gate(has_car, detections)
            
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
    rocket_chat_webhook = os.getenv('ROCKET_CHAT_WEBHOOK', None)
    car_stationary_seconds = int(os.getenv('CAR_STATIONARY_SECONDS', '3'))
    
    # Configurar ROI de exclusao (area do estacionamento, por exemplo)
    roi_exclude = None
    roi_x1 = os.getenv('ROI_EXCLUDE_X1', None)
    roi_y1 = os.getenv('ROI_EXCLUDE_Y1', None)
    roi_x2 = os.getenv('ROI_EXCLUDE_X2', None)
    roi_y2 = os.getenv('ROI_EXCLUDE_Y2', None)
    
    if all([roi_x1, roi_y1, roi_x2, roi_y2]):
        roi_exclude = (int(roi_x1), int(roi_y1), int(roi_x2), int(roi_y2))
        logger.info(f"ROI de exclusao configurada: {roi_exclude}")
    
    # Criar e executar sistema
    system = GateDetectionSystem(
        dvr_host=dvr_host,
        dvr_port=dvr_port,
        dvr_user=dvr_user,
        dvr_pass=dvr_pass,
        camera_index=camera_index,
        gate_api_url=gate_api_url,
        gate_cooldown_seconds=gate_cooldown_seconds,
        confidence_threshold=confidence_threshold,
        rocket_chat_webhook=rocket_chat_webhook,
        car_stationary_seconds=car_stationary_seconds,
        roi_exclude=roi_exclude
    )
    
    system.run()


if __name__ == '__main__':
    main()
