#!/bin/bash

cd /opt/claude/projects/printbuddy-website
git add .
git commit -m "Updated website"
git push

cd /opt/claude/projects/printbuddy-wiki
git add .
git commit -m "Updated Wiki"
git push

cd /opt/claude/projects/printbuddy-sponsors-portal
git add .
git commit -m "Updated portal"
git push
