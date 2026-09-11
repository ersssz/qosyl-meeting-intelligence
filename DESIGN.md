---
name: Qosyl
description: Минималистичный интерфейс для проверяемых протоколов
colors:
  primary: "#0A0A0A"
  secondary: "#737373"
  tertiary: "#2563EB"
  neutral: "#FAFAFA"
  surface: "#FFFFFF"
  border: "#E5E5E5"
  warn: "#B45309"
  danger: "#B91C1C"
  ok: "#15803D"
typography:
  h1:
    fontFamily: Inter, system-ui, sans-serif
    fontSize: 2rem
    fontWeight: 600
    letterSpacing: -0.02em
  h2:
    fontFamily: Inter, system-ui, sans-serif
    fontSize: 1.25rem
    fontWeight: 600
  body-md:
    fontFamily: Inter, system-ui, sans-serif
    fontSize: 1rem
    lineHeight: 1.6
  label-caps:
    fontFamily: Inter, system-ui, sans-serif
    fontSize: 0.75rem
    letterSpacing: 0.08em
  metric:
    fontFamily: ui-monospace, SFMono-Regular, monospace
    fontSize: 2.5rem
    fontWeight: 600
rounded:
  sm: 6px
  md: 10px
spacing:
  sm: 8px
  md: 16px
  lg: 32px
components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "#FFFFFF"
    rounded: "{rounded.sm}"
    padding: 12px
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: 20px
---

## Overview

Сдержанный редакционный минимализм. Светлый фон, много воздуха,
тонкие линии вместо теней, единственный акцентный цвет — только
для действий и ссылок. Интерфейс не должен выглядеть как
дашборд: он должен выглядеть как документ.

## Colors

Монохромная основа, один акцент. Цвет несёт смысл, а не
украшает: жёлтый — отсутствующий срок, красный — нужна проверка
человеком, зелёный — подтверждено источником.

## Typography

Один шрифт Inter на весь интерфейс. Иерархия строится размером и
весом, не цветом. Числовые метрики — моноширинным.

## Layout

Одна колонка, максимальная ширина 1100px, центрирование.
Вертикальный ритм кратен 8px. Разделители — линия 1px
`{colors.border}`, не тени.

## Do's and Don'ts

- Никаких градиентов, свечений, крупных теней.
- Не более одного акцентного цвета на экран.
- Пустое поле оставлять пустым, не заполнять прочерками.
- Светлая тема: демо идёт с проектора в освещённом зале.
