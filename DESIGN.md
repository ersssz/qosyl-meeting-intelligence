---
name: Qosyl — Steppe Tech Edition
description: Технологичный интерфейс для проверяемых протоколов в визуальном языке Steppe Tech Lab
colors:
  primary: "#F1F5F9"
  secondary: "#BCCBDB"
  tertiary: "#00B4D8"
  accent: "#00D4FF"
  neutral: "#0A0E1A"
  surface: "#111827"
  surface-elevated: "#172033"
  border: "rgba(148, 163, 184, 0.15)"
  warn: "#F59E0B"
  danger: "#F43F5E"
  ok: "#22C55E"
typography:
  h1:
    fontFamily: Inter, system-ui, sans-serif
    fontSize: 2.25rem
    fontWeight: 800
    letterSpacing: -0.035em
  h2:
    fontFamily: Inter, system-ui, sans-serif
    fontSize: 1.25rem
    fontWeight: 700
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
  sm: 10px
  md: 16px
  pill: 9999px
spacing:
  sm: 8px
  md: 16px
  lg: 32px
components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "#FFFFFF"
    rounded: "{rounded.pill}"
    padding: 13px 26px
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: 20px
---

## Overview

Технологичный B2B-интерфейс в визуальном языке Steppe Tech Lab:
глубокий тёмно-синий фон, холодные поверхности, яркий cyan как
сигнал работающего AI-контура и высокая контрастность для сцены.

## Colors

Navy-основа повторяет характер Steppe Tech Lab. Cyan используется
для главного действия, активных состояний и ключевых метрик.
Жёлтый означает отсутствующий срок, красный — необходимость
проверки человеком, зелёный — подтверждение источником.

## Typography

Inter используется на всём интерфейсе. Крупные заголовки имеют
плотный вес и отрицательный трекинг; технические статусы и
числовые метрики набираются моноширинным шрифтом.

## Layout

Одна колонка шириной до 1180px. Hero, контрольные панели и
результаты образуют крупные спокойные блоки; внутри используется
восьмипиксельный ритм и тонкие полупрозрачные границы.

## Do's and Don'ts

- Градиент допустим только в hero и главном действии.
- Cyan — единственный декоративный акцентный цвет.
- Пустое поле оставлять пустым, не заполнять прочерками.
- Не снижать контраст текста ради декоративности.
