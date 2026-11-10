"""Herramientas de proyección bajo demanda; no inicia procesos ni conexiones."""

from farmared.proyeccion.consumidor import sincronizar
from farmared.proyeccion.reconstruccion import reconstruir_grafo
from farmared.proyeccion.verificacion import verificar_proyeccion

__all__ = ['sincronizar', 'reconstruir_grafo', 'verificar_proyeccion']
