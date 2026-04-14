Sistema RAG

- Usamos uv, docker compose y docker para el desarrollo

- El objetivo es crear un sistema de recuperación de información (RAG) que permita a los usuarios consultar información sobre un negocio local de manera conversacional.

- La temperatura se configura en 0.3 para que la respuesta sea más determinista.


0. Imports
    import os
    from dotenv import load_dotenv
    from langchain_ollama import ChatOllama, OllamaEmbeddings 
    from langchain_community.vectorstores import FAISS
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.runnables import RunnablePassthrough
    import gradio as gr

1. Preparación del Entorno

    Instalación de dependencias: Asegúrate de tener instaladas las librerías necesarias para el procesamiento local:

        langchain-ollama (para el modelo y los embeddings).

        faiss-cpu (para el almacenamiento vectorial).

        gradio (para la interfaz de usuario).

    Servidor Ollama: Mantén el servicio de Ollama activo y el modelo qwen3:8b descargado localmente.

2. Ingesta y Fragmentación de Datos

    Carga del documento: Lee el archivo de texto que contiene toda la información operativa del negocio (productos, precios, horarios, políticas).

    Segmentación (Chunking): Utiliza RecursiveCharacterTextSplitter para dividir el texto en fragmentos de 500 caracteres con un solapamiento (overlap) pequeño. Esto garantiza que la información no se corte abruptamente y la IA mantenga el contexto entre fragmentos.

3. Creación de la Base de Datos Vectorial

    Generación de Embeddings: Convierte los fragmentos de texto en vectores numéricos utilizando OllamaEmbeddings.

    Indexación con FAISS: Almacena estos vectores en una base de datos FAISS. Esto permitirá realizar búsquedas por "similitud semántica", encontrando la respuesta por el significado de la pregunta y no solo por palabras clave exactas.

4. Configuración del Retriever y Lógica de Respuesta

    Definición del Retriever: Configura el sistema para que, ante cada consulta, recupere los 4 fragmentos más relevantes de la base de datos vectorial.

    Diseño del Prompt (Instrucciones de Sistema): Establece reglas estrictas mediante un ChatPromptTemplate. El asistente debe:

        Responder únicamente basándose en el contexto recuperado.

        Si la respuesta no está en el texto, debe admitirlo honestamente.

        Sugerir contacto con un humano si no puede resolver la duda.

5. Construcción de la Cadena (Chain)

    Ensamblaje con LCEL: Conecta los componentes (Retriever -> Prompt -> Modelo -> Output Parser) usando el lenguaje de expresión de LangChain.

    Manejo de Contexto: Usa RunnablePassthrough para asegurar que la pregunta del usuario y los documentos recuperados fluyan correctamente hacia el modelo de lenguaje.

6. Interfaz de Usuario e Implementación

    Despliegue con Gradio: Crea una función de respuesta que reciba el texto del usuario y devuelva la salida del asistente.

    Diseño de Experiencia: Configura la interfaz de chat en Gradio para incluir ejemplos de preguntas frecuentes y una visualización clara para el cliente final.

- Se menciona por defecto unos chunks de 500 caracteres con un solapamiento de 50 caracteres. pero se puede ajustar según las necesidades. por ejemplo, estudiar la viavilidad de generar chunks dinamicos en funcion del largo de un parrafo o un titulo.

- La informacion del negocio va a ser actualizada periodicamente, por lo que se debe considerar una forma de actualizar la base de datos vectorial.

- Se debe considerar la posibilidad de agregar mas documentos a la base de datos vectorial, por lo que se debe considerar una forma de agregar mas documentos sin tener que recrear la base de datos vectorial completa.

- Se considera que la informacion del negocio se encuentra en un archivo markdown, por lo que se debe considerar una forma de leer el archivo y extraer la informacion.

- Se considera la posibilidad de tener archivos markdown en carpetas separadas y referenciados entre si. Como por ejemplo lo hace Obsidian.

- Se debe considerar la posibilidad de tener archivos markdown que referencien a otros archivos markdown, por lo que se debe considerar una forma de leer los archivos y extraer la informacion de los archivos referenciados.
