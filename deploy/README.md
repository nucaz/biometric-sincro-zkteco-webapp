# Empaquetado y despliegue

| Carpeta | Qué produce | Probado en esta sesión |
|---|---|---|
| [`windows_desktop/`](windows_desktop/README.md) | `ZKTecoAttendanceSystem_Setup_X.Y.Z.0.exe` -- instalador de la app de escritorio (PyInstaller + Inno Setup) | Sí, de punta a punta: build, instalación silenciosa, registro en "Agregar o quitar programas", ejecución, desinstalación |
| [`linux_server/`](linux_server/README.md) | Servicio systemd del panel central + PostgreSQL, para Debian/Ubuntu | No -- sin servidor Linux disponible en esta sesión. Sintaxis validada, lógica revisada con cuidado |
| [`windows_server/`](windows_server/README.md) | El mismo panel central como Tareas Programadas de Windows, con SQLite o apuntando a una BD externa | Sí, de punta a punta salvo el registro final de las tareas (requiere sesión con privilegios de Administrador que esta sesión no tiene) |
| [`docs/`](docs/) | Guías de instalación ilustradas en PDF (Windows y Linux) + diagrama de arquitectura para draw.io | Generadas con `fpdf2`, sin errores de compilación |

## Guías y diagramas

- [`docs/instalacion_windows_server.pdf`](docs/instalacion_windows_server.pdf) --
  requisitos y pasos para instalar el panel en Windows Server, con diagrama
  de flujo y solución de problemas.
- [`docs/instalacion_linux_server.pdf`](docs/instalacion_linux_server.pdf) --
  lo mismo para Debian/Ubuntu.
- [`docs/architecture.drawio`](docs/architecture.drawio) -- diagrama de
  arquitectura completo (relojes, sync, base de datos, panel web,
  navegador) para abrir en [app.diagrams.net](https://app.diagrams.net)
  (draw.io) o la extensión de VS Code.

Estos PDFs no son capturas de un asistente gráfico -- la instalación en
servidor es por línea de comandos, así que en vez de fotos usan diagramas
vectoriales de cada paso. Se generan con
[`docs/generate_install_pdfs.py`](docs/generate_install_pdfs.py); vuelve a
correrlo (`venv\Scripts\python deploy\docs\generate_install_pdfs.py`) cada
vez que cambien los pasos de instalación, para que la documentación no se
desactualice.

## Regla de oro

Los usuarios finales **nunca** reciben el código fuente ni un `venv` --
solo el instalador (`windows_desktop`) o el servicio ya corriendo
(`linux_server` / `windows_server`). La única forma de sacar una versión
nueva es editar el código fuente y volver a correr el script de build
correspondiente. `VERSION` en la raíz del proyecto controla el número de
versión del instalador de escritorio.

## Cómo sacar una versión nueva

Cada release del instalador de escritorio queda trazado a un commit
concreto de este repositorio -- nunca se genera ni se distribuye a mano
fuera de este flujo:

1. Haz los cambios de código que correspondan y súbelos a `main`.
2. Sube el número en [`VERSION`](../VERSION) (ej. `1.0.0` -> `1.1.0`).
3. Agrega una entrada nueva en [`CHANGELOG.md`](../CHANGELOG.md) con lo
   que cambió.
4. Haz commit de `VERSION` + `CHANGELOG.md`.
5. Etiqueta ese commit y súbelo:
   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```
6. El workflow [`release-desktop.yml`](../.github/workflows/release-desktop.yml)
   se dispara solo: compila el instalador (PyInstaller + Inno Setup) en un
   runner limpio de GitHub Actions -- no en tu PC -- y publica un
   [Release](https://github.com/nucaz/biometric-sincro-zkteco-webapp/releases)
   con el `.exe` adjunto. Si el tag no coincide con el `VERSION` del
   commit, el build falla a propósito (evita publicar una versión mal
   etiquetada).

Los servidores (`windows_server` / `linux_server`) no usan tags todavía --
se actualizan copiando el código más reciente de `main` y volviendo a
correr el script de instalación (ver cada README). Si más adelante quieres
versionar también el panel web por releases, lo agregamos igual.
