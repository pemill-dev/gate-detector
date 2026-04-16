# Sistema de Detecção de Carros e Abertura Automática de Portão

Este projeto é uma solução completa em Python e Docker para monitorar uma câmera de DVR Intelbras (modelo iMHDX 3132) via ONVIF, detectar carros em tempo real usando Inteligência Artificial (YOLOv8) e enviar uma requisição POST para abrir um portão automaticamente.

## Arquitetura da Solução

O sistema funciona da seguinte maneira:
1. Conecta-se à DVR Intelbras via protocolo ONVIF para obter a URL do stream RTSP da câmera especificada.
2. Captura os frames de vídeo em tempo real usando OpenCV.
3. Processa cada frame com o modelo YOLOv8 (versão nano para melhor performance) para detectar veículos.
4. Monitora a posição do veículo e aguarda que ele fique parado por um tempo configurável.
5. Ao detectar um veículo parado, verifica se o portão está fechado.
6. Se as condições forem atendidas, envia uma requisição POST para a API de abertura do portão.
7. Aguarda o tempo configurado antes de permitir uma nova abertura.
8. Envia notificação com screenshot para Rocket.Chat (opcional).

## Estrutura de Arquivos

- `gate_detector_app.py`: O script principal em Python que contém toda a lógica.
- `requirements.txt`: Lista de dependências Python.
- `Dockerfile`: Instruções para construir a imagem Docker otimizada.
- `docker-compose.yml`: Configuração para facilitar o deploy e gerenciamento.
- `.env.example`: Exemplo de arquivo de variáveis de ambiente (copie para `.env` e configure).

## Como fazer o Deploy no Coolify

Como você possui um servidor rodando Coolify na rede interna da empresa, o processo de deploy é bastante simples. Siga os passos abaixo:

### Opção 1: Deploy via Repositório Git (Recomendado)

1. Crie um repositório Git (GitHub, GitLab, Bitbucket, etc.) e adicione os arquivos fornecidos.
2. No painel do Coolify, vá em **Projects** e crie um novo projeto ou selecione um existente.
3. Clique em **New Resource** e selecione **Public Repository** (ou Private, dependendo de onde você hospedou).
4. Insira a URL do seu repositório e selecione a branch principal.
5. O Coolify detectará automaticamente o `Dockerfile` ou `docker-compose.yml`.
6. Na seção **Environment Variables**, configure as variáveis necessárias (veja a seção abaixo).
7. Clique em **Deploy**.

### Opção 2: Deploy via Docker Compose (Direto no Coolify)

1. No painel do Coolify, vá em **Projects** e selecione seu projeto.
2. Clique em **New Resource** e selecione **Docker Compose**.
3. Cole o conteúdo do arquivo `docker-compose.yml` fornecido.
4. Na seção **Environment Variables**, configure as variáveis necessárias.
5. Clique em **Deploy**.

## Variáveis de Ambiente

O sistema é totalmente configurável através de variáveis de ambiente. Aqui estão as variáveis disponíveis:

| Variável | Descrição | Tipo |
|----------|-------------|------|
| `DVR_HOST` | Endereço IP da DVR Intelbras na rede interna | String |
| `DVR_PORT` | Porta de acesso ONVIF/HTTP da DVR | Inteiro |
| `DVR_USER` | Usuário de acesso à DVR | String |
| `DVR_PASS` | Senha de acesso à DVR | String |
| `CAMERA_INDEX` | Número da câmera a ser monitorada (1-based) | Inteiro |
| `GATE_API_URL` | URL completa da rota POST para abrir o portão | String |
| `GATE_COOLDOWN_SECONDS` | Tempo em segundos que o portão leva para fechar | Inteiro |
| `CONFIDENCE_THRESHOLD` | Nível de confiança mínimo para a IA considerar como veículo (0.0 a 1.0) | Float |
| `CAR_STATIONARY_SECONDS` | Tempo em segundos que o veículo deve ficar parado antes de abrir o portão | Inteiro |
| `ROCKET_CHAT_WEBHOOK` | URL do webhook do Rocket.Chat para notificações (opcional) | String |

### Exemplo de Configuração

Copie o arquivo `.env.example` para `.env` e preencha com suas informações:

```bash
cp .env.example .env
```

Edite o arquivo `.env` com suas credenciais e URLs específicas.

## Monitoramento e Logs

O sistema foi projetado para ser resiliente e manter logs detalhados de todas as operações.

- Os logs são salvos no diretório `/app/logs/gate_detector.log` dentro do container.
- No `docker-compose.yml`, configuramos um volume `./logs:/app/logs` para que os logs persistam mesmo se o container for reiniciado.
- Você pode visualizar os logs em tempo real no painel do Coolify, na aba **Logs** do seu recurso.

## Recursos Principais

✅ **Detecção de Veículos com IA**
- Utiliza YOLOv8 nano para detecção em tempo real
- Detecta carros, caminhões, ônibus e motos
- Configurável para ajustar sensibilidade

✅ **Detecção de Parada**
- Monitora a posição do veículo
- Só abre portão se veículo ficar parado por tempo configurável
- Evita abertura desnecessária de veículos em movimento

✅ **Integração com Rocket.Chat**
- Envia notificação com screenshot quando portão abre
- Inclui timestamp e detalhes da detecção

✅ **Resiliente e Confiável**
- Reconexão automática em caso de falha
- Logs detalhados de todas as operações
- Suporte para ONVIF com fallback automático

## Resolução de Problemas Comuns

### Falha ao conectar via ONVIF
Se o sistema não conseguir obter a URL do stream via ONVIF, ele tentará usar uma URL de fallback padrão da Intelbras. Certifique-se de que o protocolo ONVIF está ativado nas configurações de rede da sua DVR.

### Falsos Positivos
Se o portão estiver abrindo para objetos que não são veículos, você pode aumentar o valor da variável `CONFIDENCE_THRESHOLD` para `0.6` ou `0.7`.

### Alta Utilização de CPU
O processamento de vídeo com IA consome recursos. O modelo YOLOv8 nano (`yolov8n.pt`) foi escolhido por ser o mais leve e rápido. No `docker-compose.yml`, limitamos o uso a 2 CPUs e 2GB de RAM para evitar que o container afete outros serviços no seu servidor Coolify.

### Veículos em Movimento Acionam Abertura
Ajuste a variável `CAR_STATIONARY_SECONDS` para um valor maior (ex: 5 segundos) para garantir que apenas veículos realmente parados acionem a abertura.


## Referências

[1] Documentação Ultralytics YOLOv8: https://docs.ultralytics.com/
[2] Biblioteca Python ONVIF: https://github.com/quatanium/python-onvif
[3] OpenCV Documentation: https://docs.opencv.org/
