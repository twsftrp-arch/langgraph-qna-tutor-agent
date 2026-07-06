#!/bin/bash
set -e

cleanup() {
    echo "Switching gh auth back to trinity-mathslab..."
    gh auth switch -u trinity-mathslab
}
trap cleanup EXIT

echo "Initializing git repository..."
git init
git add .
git commit -m "init: Add LangGraph QnA Tutor Agent for demo day"

echo "Switching gh auth to twsftrp-arch..."
gh auth switch -u twsftrp-arch

echo "Creating public GitHub repository twsftrp-arch/langgraph-qna-tutor-agent..."
# --push flag pushes the current branch to the new repo automatically
gh repo create twsftrp-arch/langgraph-qna-tutor-agent --public --source=. --push

echo "Done! 🎉"
