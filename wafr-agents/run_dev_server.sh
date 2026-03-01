#!/bin/bash
# Run WAFR dev server with cloud202 AWS profile

export AWS_PROFILE=cloud202
export AWS_DEFAULT_REGION=us-east-1

echo "🚀 Starting WAFR AgentCore Dev Server"
echo "   AWS Profile: $AWS_PROFILE"
echo "   AWS Region: $AWS_DEFAULT_REGION"
echo ""

agentcore dev
