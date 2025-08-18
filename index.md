---
layout: default
title: "Chengyu Bites"
---

## Episodes
{% for post in site.posts %}
- **<a href="{{ post.url | relative_url }}">{{ post.title }}</a>**  
  {% if post.description %}{{ post.description }}{% endif %}  
  {% if post.audio_url %}<audio controls preload="none" src="{{ post.audio_url }}"></audio>{% endif %}
{% endfor %}
