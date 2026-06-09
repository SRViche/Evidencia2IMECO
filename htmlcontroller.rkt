#lang racket

; htmlcontroller.rkt
; Autores: Ivan Burrola, Alberto Lopez, Axel Lugo, Sebastian Viche
; Materia: Implementacion de metodos computacionales

(require web-server/servlet-env
         web-server/http
         web-server/http/response-structs
         net/url
         json
         racket/runtime-path
         "mainbase.rkt")

(define-runtime-path BASE-DIR ".")

(define cors-headers
  (list (make-header #"Access-Control-Allow-Origin"  #"*")
        (make-header #"Access-Control-Allow-Methods" #"POST, GET, OPTIONS")
        (make-header #"Access-Control-Allow-Headers" #"Content-Type")))

(define (json-ok jsexpr)
  (response/full 200 #"OK" (current-seconds)
                 #"application/json; charset=utf-8"
                 cors-headers
                 (list (jsexpr->bytes jsexpr))))

(define (json-err code msg)
  (response/full code (string->bytes/utf-8 msg) (current-seconds)
                 #"application/json; charset=utf-8"
                 cors-headers
                 (list (jsexpr->bytes (hasheq 'error msg)))))

(define (mime-for name)
  (cond [(string-suffix? name ".png")  #"image/png"]
        [(string-suffix? name ".jpg")  #"image/jpeg"]
        [(string-suffix? name ".jpeg") #"image/jpeg"]
        [(string-suffix? name ".gif")  #"image/gif"]
        [(string-suffix? name ".webp") #"image/webp"]
        [else #"application/octet-stream"]))

(define (->str v) (if (string? v) v (symbol->string v)))

(define (my-handler req)
  (define segs
    (filter (λ (s) (and (string? s) (non-empty-string? s)))
            (map path/param-path (url-path (request-uri req)))))
  (define method (bytes->string/utf-8 (request-method req)))

  (cond
    ;; GET / → index.html
    [(and (null? segs) (equal? method "GET"))
     (define p (build-path BASE-DIR "index.html"))
     (if (file-exists? p)
         (response/full 200 #"OK" (current-seconds)
                        #"text/html; charset=utf-8" cors-headers
                        (list (file->bytes p)))
         (json-err 404 "index.html no encontrado"))]

    ;; OPTIONS /api/process → CORS preflight
    [(and (equal? segs '("api" "process")) (equal? method "OPTIONS"))
     (response/full 204 #"No Content" (current-seconds)
                    #"text/plain" cors-headers '())]

    ;; POST /api/process → procesar imagen
    [(and (equal? segs '("api" "process")) (equal? method "POST"))
     (with-handlers
         ([exn:fail? (λ (e)
                       (printf "Error /api/process: ~a\n" (exn-message e))
                       (json-err 500 (exn-message e)))])
       (define raw (request-post-data/raw req))
       (unless raw (error "Sin datos POST"))
       (define data     (bytes->jsexpr raw))
       (define img      (hash-ref data 'image    #f))
       (define filter-n (hash-ref data 'filter   "negative"))
       (define method-n (hash-ref data 'approach "sequential"))
       ;; workers: viene del slider; si no está presente o no es paralelo,
       ;; process-request lo ignora.
       (define workers  (hash-ref data 'workers  #f))
       (unless img (error "Falta 'image' en JSON"))
       (define-values (b64 ms)
         (process-request (->str img)
                          (->str filter-n)
                          (->str method-n)
                          #:workers (and workers (inexact->exact (round workers)))))
       (if (equal? b64 "")
           (json-err 404 (string-append "Imagen no encontrada: " (->str img)))
           (json-ok (hasheq 'base64Image b64 'timeMs ms))))]

    ;; GET /<archivo estático>
    [(and (= (length segs) 1) (equal? method "GET"))
     (define p (build-path BASE-DIR (car segs)))
     (if (file-exists? p)
         (response/full 200 #"OK" (current-seconds)
                        (mime-for (car segs)) cors-headers
                        (list (file->bytes p)))
         (json-err 404 (string-append "No encontrado: " (car segs))))]

    [else (json-err 404 "Ruta no encontrada")]))

(printf "Directorio del proyecto: ~a\n" BASE-DIR)
(printf "Servidor en http://127.0.0.1:8080\n")

(serve/servlet
 my-handler
 #:port            8080
 #:listen-ip       "127.0.0.1"
 #:servlet-path    "/"
 #:servlet-regexp  #rx""
 #:launch-browser? #f
 #:command-line?   #t
 #:extra-files-paths '())
