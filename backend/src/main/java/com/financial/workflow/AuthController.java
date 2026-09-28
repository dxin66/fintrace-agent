package com.financial.workflow;

import jakarta.servlet.http.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

  private final DataMapper db;
  private final BCryptPasswordEncoder encoder;

  public AuthController(DataMapper db, BCryptPasswordEncoder encoder) {
    this.db = db;
    this.encoder = encoder;
  }

  record Credentials(
    @NotBlank @Pattern(regexp = "[a-zA-Z0-9_]{3,40}") String username,
    @Size(min = 8, max = 72) @NotNull String password
  ) {}

  @GetMapping("/csrf")
  public Map<String, String> csrf(CsrfToken token) {
    return Map.of("token", token.getToken(), "header", token.getHeaderName());
  }

  @PostMapping("/register")
  public Map<String, Object> register(@Valid @RequestBody Credentials body) {
    Map<String, Object> row = new HashMap<>();
    row.put("username", body.username());
    row.put("password_hash", encoder.encode(body.password()));
    db.insertUser(row);
    return Map.of("id", row.get("id"), "username", body.username());
  }

  @PostMapping("/login")
  public Map<String, Object> login(
    @Valid @RequestBody Credentials body,
    HttpServletRequest request,
    HttpServletResponse response
  ) {
    var row = db.user(body.username());
    if (
      row == null ||
      !encoder.matches(body.password(), row.get("password_hash").toString())
    ) throw new ResponseStatusException(
      HttpStatus.UNAUTHORIZED,
      "账号或密码错误"
    );
    var context = SecurityContextHolder.createEmptyContext();
    context.setAuthentication(
      new UsernamePasswordAuthenticationToken(
        row.get("id").toString(),
        null,
        List.of(new SimpleGrantedAuthority("ROLE_USER"))
      )
    );
    if (request.getSession(false) != null) request.changeSessionId();
    SecurityContextHolder.setContext(context);
    new HttpSessionSecurityContextRepository().saveContext(
      context,
      request,
      response
    );
    return Map.of("id", row.get("id"), "username", row.get("username"));
  }

  @GetMapping("/me")
  public Map<String, Object> me(Authentication auth) {
    return Map.of("id", Long.parseLong(auth.getName()));
  }

  @PostMapping("/logout")
  public Map<String, Boolean> logout(HttpServletRequest request) {
    var session = request.getSession(false);
    if (session != null) session.invalidate();
    SecurityContextHolder.clearContext();
    return Map.of("ok", true);
  }

  public static long owner(Authentication auth) {
    return Long.parseLong(auth.getName());
  }
}
