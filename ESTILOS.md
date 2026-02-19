# Guía de estilos – Centro de Fisioterapia

Todos los estilos están en `static/css/theme.css` y se complementan entre sí. Aquí se explica **qué hace cada uno** y dónde se usa.

---

## 1. Variables (`:root`)

| Variable | Uso |
|----------|-----|
| `--primary`, `--primary-hover` | Color principal (teal): botones “Agendar”, enlaces activos, barras. |
| `--primary-light` | Fondos suaves (hover en tablas, inputs focus). |
| `--secondary`, `--accent` | Gradientes y acentos (navbar brand, modal focus). |
| `--bg-body` | Fondo de la página: gradiente suave verde-azul. |
| `--glass-bg`, `--glass-border` | Efecto glass: navbar y cards semitransparentes. |
| `--text`, `--text-muted` | Texto principal y secundario. |
| `--shadow-sm`, `--shadow-md`, `--shadow-lg` | Sombras en cards y botones. |
| `--radius-sm`, `--radius-md`, `--radius-lg` | Bordes redondeados (12px, 18px, 24px). |
| `--transition` | Duración y curva de las animaciones. |

Cambiando estas variables se actualiza el aspecto de todo el sitio.

---

## 2. Base y tipografía

- **`body`**: Fondo con gradiente (`--bg-body`), fuente Outfit, color de texto, `min-height: 100vh`, sin scroll horizontal.
- **`html`**: `scroll-behavior: smooth` para desplazamiento suave al hacer clic en enlaces internos.

---

## 3. Animaciones globales

| Nombre | Qué hace |
|--------|----------|
| **`fadeInUp`** | El elemento aparece subiendo y pasando de transparente a opaco. |
| **`fadeIn`** | Solo cambia la opacidad de 0 a 1. |
| **`float`** | Movimiento suave arriba/abajo (p. ej. imagen del hero). |
| **`shimmer`** | Efecto de brillo que recorre el elemento (reservado para uso futuro). |
| **`pulse-soft`** | Sombra que se expande y desvanece (reservado para botones/cards). |

**Clases de uso directo:**

- **`.reveal`**: Aplica `fadeInUp` al cargar; ideal para secciones y bloques de contenido.
- **`.reveal-delay-1`, `.reveal-delay-2`, `.reveal-delay-3`**: Mismo efecto con un pequeño retraso (entrada escalonada).
- **`.floating-animation`**: Aplica la animación `float` (p. ej. imagen principal del inicio).

---

## 4. Navbar

- Fondo tipo glass (`--glass-bg`) con `backdrop-filter: blur`.
- Borde inferior suave y sombra ligera.
- **`.navbar-brand span`**: Texto del logo con gradiente primario → secundario.
- **`.nav-link`**: Color gris que al hover pasa a primario; subrayado que crece de centro a los lados.

---

## 5. Botones

- **`.btn-success`**: Fondo primario, sombra y ligera elevación al hover (`translateY(-2px)`). Se usa en “Agendar”, “Ingresar”, “Crear cuenta”.
- **`.btn-primary`**: Mismo tipo de transición y elevación al hover.
- **`.btn-outline-success`**: Borde grueso y misma elevación al hover.

---

## 6. Cards (glass)

- **`.card`**: Fondo glass, blur, borde suave, bordes redondeados (`--radius-lg`) y sombra.
- **`.card:hover`**: Sube un poco y aumenta la sombra.
- **`.card-header`**: Esquinas superiores redondeadas y borde inferior discreto.

---

## 7. Tarjetas de servicio

- **`.card-servicio`**: Misma línea visual que el resto: fondo glass, franja superior en gradiente primario → secundario.
- **`.card-servicio:hover`**: Elevación y sombra más marcada.
- **`.card-servicio .card-content`**: Contenido encima del fondo; texto con color del tema.
- **`.card-servicio .btn-outline-info`**: Borde y texto primarios; al hover, fondo muy suave primario.

Sustituyen el antiguo estilo oscuro con borde neon para que encajen con el resto de la web.

---

## 8. Modal “Agendar”

- **`.modal-content-original`**: Fondo oscuro con blur y borde redondeado grande.
- **`.title-original`**: Título del modal en blanco.
- **`.message-original`**: Subtítulo en gris claro.
- **`.input-original`**: Campos con fondo semitransparente y borde sutil; al hacer focus, borde y sombra en color acento.
- **`.submit-original`**: Botón de envío con gradiente primario → secundario y ligera elevación al hover.

---

## 9. Formularios (login, registro)

- **`.form-control`**: Bordes redondeados y borde gris claro.
- **`.form-control:focus`**: Borde y sombra en color primario.

---

## 10. Badges y alertas

- **`.badge`**: Bordes redondeados y peso de fuente consistente.
- **`.alert`**: Sin borde, sombra suave y animación `fadeInUp` al mostrarse.

---

## 11. Tablas

- **`.table thead th`**: Fondo `--primary-light`, sin borde.
- **`.table-hover tbody tr:hover`**: Fila con fondo primario muy suave.

---

## 12. Scrollbar

- Barra fina, color gris claro, más oscura al hover. Afecta a toda la página.

---

## 13. Clases de utilidad

| Clase | Uso |
|-------|-----|
| **`.text-gradient`** | Texto con gradiente primario → secundario (p. ej. “Recuperación” en el hero). |
| **`.shadow-soft`** | Aplica `--shadow-md`. |
| **`.shadow-2xl`** | Sombra más grande (hero, imágenes). |
| **`.hero-blob`** | Círculos de fondo borrosos y semitransparentes en el hero. |

---

## Cómo aplicar el tema en una página nueva

1. Extender `base.html` (ya carga `theme.css`).
2. Usar **`.reveal`** en bloques que quieras que entren con animación.
3. Usar **`.card`** para contenedores tipo “caja”.
4. Usar **`.btn-success`** para la acción principal y **`.btn-outline-*`** para la secundaria.
5. Evitar estilos inline; preferir clases de `theme.css` o de Bootstrap.
6. Para títulos destacados, usar **`.text-gradient`** en una palabra o frase.

Si quieres cambiar solo colores o radios, edita las variables al inicio de `theme.css`.
