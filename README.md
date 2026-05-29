# Catalogo-Peliculas-Biblioteca-Vasconcelos


todo ha de correr local 

Documento de Especificación de Trabajo Pendiente (Versión Tech Stack: Python/Quarto/ObservableJS)
Proyecto: Sistema de Gestión de Cine/Películas (Catalogo-Peliculas-Biblioteca-Vasconcelos)
Objetivo General: Desarrollar y refactorizar el sistema utilizando Python para el backend, Quarto para la presentación y ObservableJS para la interactividad, enfocándose en mejorar la usabilidad, la robustez de la extracción de datos de PDFs y la integración de servicios externos.
Stack Tecnológico Principal:
Backend: Python (Framework a definir, ej: FastAPI/Flask)
Frontend/Presentación: Quarto
Interactividad/Visualización: ObservableJS
Herramienta de Infraestructura: Windsurf (para gestión del MCP local)
1. Contexto y Estado Actual
El proyecto se centra en la gestión del catálogo de películas, almacenado principalmente en archivos PDF. Se requiere una arquitectura robusta que permita la extracción de metadatos de manera dinámica, la integración de datos externos (OMDB) y una interfaz de usuario moderna y reactiva.
2. Tareas Pendientes Detalladas
Las tareas se dividen en cuatro pilares funcionales, alineados con el stack tecnológico.
A. Arquitectura Backend (Python) y Infraestructura (Windsurf)
Objetivo: Establecer la base sólida para la gestión de datos, procesamiento y comunicación entre servicios.
Tareas Específicas:
Configuración del MCP Local: Utilizar Windsurf para configurar y desplegar el MCP (Microservice/Middleware) local. Este servicio será el punto central de comunicación entre el frontend, la lógica de extracción y las fuentes de datos.
Desarrollo del API Backend: Implementar los endpoints de la API en Python (usando FastAPI/Flask/etc.) para manejar las solicitudes del frontend y comunicarse con el MCP.
Módulo de Procesamiento de PDFs: Desarrollar la lógica en Python para manejar la lectura, parsing y extracción de datos de los archivos PDF.
B. Extracción y Robustecida de Datos (Python Backend/MCP)
Objetivo: Asegurar la capacidad para encontrar y extraer metadatos de películas de manera dinámica y fiable.
Tareas Específicas:
Búsqueda Dinámica de Catálogo: Implementar la lógica en el backend para que, al recibir una consulta, pueda buscar dinámicamente las películas dentro del MCP local, basándose en la estructura de los PDFs.
Mapeo de Metadatos: Definir y codificar la estructura de los datos (JSON/Pydantic) para asegurar que los metadatos extraídos de los PDFs sean consistentes y utilizables por el frontend.
C. Integración de Servicios Externos (Python Backend)
Objetivo: Enriquecer el catálogo con información externa (director, idioma).
Tareas Específicas:
Integración OMDB: Desarrollar un módulo en Python para interactuar con la API de OMDB.
Búsqueda Bilingüe: Implementar la lógica para realizar búsquedas en OMDB enfocadas en películas en español y asegurar la recuperación precisa del director asociado a cada resultado.
Consolidación de Datos: Crear una función en Python que consolide los datos extraídos de los PDFs y los datos obtenidos de OMDB en un formato unificado para el frontend.
D. Frontend y Visualización (Quarto/ObservableJS)
Objetivo: Crear una interfaz de usuario interactiva y visualmente atractiva para consumir los datos procesados.
Tareas Específicas:
Estructura del Proyecto Quarto: Definir la estructura de archivos y la configuración de Quarto para manejar la presentación del catálogo.
Desarrollo de Componentes ObservableJS: Implementar los componentes interactivos clave utilizando ObservableJS. Esto incluye:
La interfaz de búsqueda y filtrado del catálogo.
La visualización dinámica de los resultados obtenidos del backend.
La presentación clara de la información enriquecida (incluyendo director de OMDB).
Conexión Backend-Frontend: Establecer la comunicación asíncrona (ej: usando fetch o axios) entre ObservableJS y los endpoints de Python.
E. Finalización de la Extracción (Índices de PDF)
Objetivo: Completar la funcionalidad de navegación interna dentro de los documentos.
Tareas Específicas:
Análisis del Índice: Analizar la estructura de los PDFs para identificar la ubicación exacta de la tabla de contenido/índice.
Implementación del Mapeo: Desarrollar la lógica en Python para extraer el índice y mapearlo a las páginas o secciones correspondientes, permitiendo al usuario saltar directamente a la sección deseada dentro del PDF.
3. Requisitos Técnicos y Entregables Esperados
Componente
Tecnología Clave
Entregable Esperado
Backend Core
Python (FastAPI/Flask)
API RESTful endpoints funcionales para CRUD y búsqueda.
Infraestructura
Windsurf, MCP
MCP local corriendo y documentado.
Data Processing
Python Libraries (PyPDF parsing)
Módulo de extracción de datos robusto y validado.
External Data
Python (Requests/OMDB)
Módulo de integración con OMDB para datos de director/idioma.
Frontend
Quarto, ObservableJS
Aplicación web interactiva que consume datos del backend y presenta la información de manera dinámica.
Final
N/A
Sistema completo y funcional que permite buscar, filtrar, y visualizar información enriquecida de películas.
4. Priorización Sugerizada
Faseo Configuración de Windsurf y el Backend Python base.
media Desarrollo de la lógica de extracción de PDFs (básico).
media Integración de la API de OMDB.
media/alta Desarrollo de la interfaz interactiva en ObservableJS y conexión con el backend.
baja/compleja Implementación del mapeo del índice de los PDFs.
¿Por qué es mejor esta versión?
Lenguaje Específico: Menciona explícitamente Python en cada sección, lo que es crucial para un LLM.
Roles Claros: Define claramente qué hace el Backend (Python), qué hace el Frontend (Quarto/ObservableJS) y qué hace la herramienta de infraestructura (Windsurf).
Flujo de Datos: Describe el camino de la información: PDF $\rightarrow$ MCP $\rightarrow$ Python API $\rightarrow$ OMDB API $\rightarrow$ ObservableJS $\rightarrow$ Usuario. Esto es vital para la arquitectura.
Tareas Técnicas Detalladas: Las tareas no son solo "mejorarregar", sino "Implementar lógica de mapeo", "Desarrollar componentes interactivos".