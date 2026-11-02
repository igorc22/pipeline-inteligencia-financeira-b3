"""Configuração global dos testes.

Desliga o tracing do LangSmith antes de qualquer import do projeto: com LANGSMITH_TRACING=true
no .env, cada tool.invoke() dos testes viraria um trace no projeto real, poluindo os dados e
fazendo os testes dependerem de rede. O load_dotenv() de config.py não sobrescreve variáveis
que já existem no ambiente, então o valor abaixo prevalece.
"""
import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
