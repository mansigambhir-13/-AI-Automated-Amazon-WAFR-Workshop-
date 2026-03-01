"use client";

import { Amplify } from 'aws-amplify';
import { cognitoUserPoolsTokenProvider } from 'aws-amplify/auth/cognito';
import { sessionStorage } from 'aws-amplify/utils';
import { Authenticator } from '@aws-amplify/ui-react';
import { Settings } from 'lucide-react';
import '@aws-amplify/ui-react/styles.css';

// Configure Amplify at module scope (not inside useEffect) — per Amplify v6 docs
Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID!,
      userPoolClientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID!,
    },
  },
});

// Use sessionStorage so token is cleared when the tab is closed
cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage);

// ---------------------------------------------------------------------------
// Custom Authenticator header — WAFR branding above the login form
// ---------------------------------------------------------------------------
function AuthHeader() {
  return (
    <div className="flex flex-col items-center gap-2 py-6">
      <Settings className="h-10 w-10 text-primary" />
      <h1 className="font-heading text-foreground text-xl font-bold leading-tight text-center">
        AWS Well-Architected Tool
      </h1>
      <p className="text-muted-foreground text-sm text-center">
        Framework Review &amp; Assessment
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AmplifyProvider — wraps the app in a Cognito authentication gate
// ---------------------------------------------------------------------------
export default function AmplifyProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Authenticator
      initialState="signIn"
      signUpAttributes={['email']}
      formFields={{
        signUp: {
          username: {
            label: 'Username',
            placeholder: 'Choose a username',
            order: 1,
          },
          email: {
            label: 'Email',
            placeholder: 'Enter your email',
            order: 2,
          },
          password: {
            label: 'Password',
            placeholder: 'Create a password',
            order: 3,
          },
          confirm_password: {
            label: 'Confirm Password',
            placeholder: 'Confirm your password',
            order: 4,
          },
        },
        signIn: {
          username: {
            label: 'Username',
            placeholder: 'Enter your username',
          },
        },
      }}
      components={{ Header: AuthHeader }}
    >
      {({ signOut: _signOut, user: _user }) => <>{children}</>}
    </Authenticator>
  );
}
