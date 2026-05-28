# CDN — Cria da Natureza

## O que é o sistema

Plataforma de gestão interna da **Cria da Natureza**, marca de cosméticos naturais e veganos. Centraliza estoque, vendas, parceiros consignados e fluxo financeiro num único lugar, com fluxo de venda via QR Code e área dedicada para cada parceira.

## A dor da cliente e como o sistema resolve

A Cria da Natureza vende em pontos próprios e por meio de **parceiras que recebem produtos em consignação**. Antes do sistema, a operação dependia de planilhas e mensagens soltas, o que gerava as seguintes dores:

- **Não sabia quanto produto estava na rua.** Cada parceira tinha um estoque informal, e era impossível responder com precisão quanto havia sido enviado, vendido ou devolvido.
  → Hoje o sistema controla envios, vendas e devoluções por parceira, mostrando em tempo real o **estoque em mãos** de cada uma e separando-o do almoxarifado central.

- **Cálculo de comissão manual e propenso a erro.** Apurar quanto cada parceira ganhou exigia revisar venda por venda.
  → A comissão é calculada **automaticamente** no momento da venda, conforme o percentual configurado por parceira, e já entra no financeiro como despesa a pagar.

- **Caixa sem padrão e sem registro confiável.** Vendas presenciais eram anotadas à mão e perdiam rastreabilidade.
  → O cliente monta o carrinho no catálogo digital, gera um **QR Code**, e a parceira (ou o admin) confirma no caixa — a venda é registrada com data, valor, desconto, método de recebimento e produto vendido, gerando recibo.

- **Falta de visão financeira.** Não havia uma forma simples de ver receita, custo, despesa, comissão e margem.
  → Há um **dashboard com KPIs mensais**, gráfico de evolução, fluxo de caixa, contas a pagar/receber, e relatórios com filtros por período. Cada parceira tem sua própria visão restrita das próprias vendas e comissões.

- **Estoque baixo passava despercebido.** Faltava produto sem aviso.
  → Alertas automáticos de **estoque mínimo** no dashboard.

- **Acesso indevido aos dados internos.** Não dava para deixar uma parceira ver o sistema todo.
  → Autenticação com dois papéis: **admin** (acesso total) e **parceiro** (acesso restrito à própria operação).

Em resumo: o sistema substitui a colcha de retalhos de planilhas, anotações e cálculos manuais por uma operação **rastreável, automática e segura**, devolvendo tempo à dona do negócio e dando às parceiras autonomia para acompanhar as próprias vendas.

## Tecnologias

Python, Flask, Jinja2, SQLAlchemy, SQLite, Flask-WTF (CSRF), Werkzeug, HTML, CSS e JavaScript.
